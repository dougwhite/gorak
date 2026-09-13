"""Connect journal processing to durable, full three-way comparison evidence."""

import json
import os
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .connection import OpenRoadConnection, require_odbc_settings
from .installation_check import check_installation
from .journal import JournalEvent, acknowledgment_store, consume_journal
from .project import ProjectError
from .project_lock import project_lock
from .safe_pull import fingerprint
from .sync_guard import binding_status
from .sync_plan import plan_project


def flush_directory(path: Path) -> None:
    """POSIX directory durability; Windows does not support directory fsync here."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def persist_comparison(directory: Path, report: dict[str, object]) -> None:
    """Flush immutable XML evidence before publishing its completion receipt."""
    for path in directory.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    report_path = directory / "comparison.json"
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    for path in sorted(
        (p for p in directory.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        flush_directory(path)
    flush_directory(directory)
    flush_directory(directory.parent)
    flush_directory(directory.parent.parent)


def reconcile_journal(
    connection: OpenRoadConnection, root: Path, limit: int = 100
) -> dict[str, object]:
    """Acknowledge only events followed by a saved disk/database agreement check.

    This does not advance common sync baselines or permit skipping future exports.
    """
    settings = require_odbc_settings(connection)
    if settings.database != connection.database:
        raise ProjectError("Journal and source-comparison database targets differ")
    with project_lock(root, "journal reconcile"):
        if binding_status(connection, root) != "verified":
            raise ProjectError(
                "Journal reconciliation requires a verified sync target binding"
            )
        health = check_installation(settings)
        if health.issues or health.installation_id is None:
            raise ProjectError(
                "Journal reconciliation requires a complete tracking inventory"
            )
        initial = fingerprint(root)
        operation: Path | None = None
        with acknowledgment_store(root / ".openroad" / "journal.sqlite3") as store:
            store.execute(
                "create table if not exists comparison_receipts "
                "(event_id integer primary key, report_path text not null)"
            )
            store.commit()

            def process(event: JournalEvent) -> None:
                nonlocal operation
                if operation is None:
                    directory = root / ".openroad" / "journal-comparisons"
                    directory.mkdir(parents=True, exist_ok=True)
                    operation = directory / uuid4().hex
                    operation.mkdir()
                    changes = plan_project(
                        connection, root, capture_dir=operation / "xml"
                    )
                    stable = fingerprint(root) == initial
                    after = check_installation(settings)
                    if after.issues or after.installation_id != health.installation_id:
                        raise ProjectError(
                            f"Tracking installation changed during comparison; events remain pending. Artifacts: {operation}"
                        )
                    if store.execute("select id from installation").fetchall() != [
                        (health.installation_id,)
                    ]:
                        raise ProjectError("Journal installation identity changed")
                    agrees = all(
                        c.action in {"unchanged", "converged"} for c in changes
                    )
                    persist_comparison(
                        operation,
                        {
                            "installation_id": health.installation_id,
                            "source_fingerprint": initial,
                            "changes": [asdict(c) for c in changes],
                            "disk_stable": stable,
                            "disk_database_agree": agrees,
                            "common_baselines_updated": False,
                        },
                    )
                    if not stable or not agrees:
                        raise ProjectError(
                            f"Source comparison needs reconciliation; events remain pending. See {operation / 'comparison.json'}"
                        )
                    if fingerprint(root) != initial:
                        raise ProjectError(
                            f"Project changed while persisting comparison; events remain pending. Artifacts: {operation}"
                        )
                # Each receipt is durable before consume_journal acknowledges its ID.
                # Later failures replay safely using fresh comparison evidence.
                with store:
                    store.execute(
                        "insert or replace into comparison_receipts values (?, ?)",
                        (
                            event.event_id,
                            str((operation / "comparison.json").relative_to(root)),
                        ),
                    )

            batch = consume_journal(settings, store, process, limit)
        return {
            "installation_id": batch.installation_id,
            "processed_events": len(batch.events),
            "comparison": str(operation / "comparison.json") if operation else None,
            "common_baselines_updated": False,
            "incremental_ready": False,
        }

"""Verify selective observation refresh against fresh full XML exports."""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from lxml import etree

from .connection import OpenRoadConnection, require_odbc_settings
from .installation_check import check_installation
from .journal import acknowledgment_store, bind_store, poll_journal
from .journal_ancestry import load_ancestry, read_ancestry, write_ancestry
from .journal_mapping import Entity, map_applications
from .journal_observation import observe_journal
from .journal_observer import checkpoint_observer, stage_observer
from .journal_rebootstrap import publish_consumer
from .journal_reconcile import flush_directory, persist_comparison
from .journal_server import consumer_identity
from .portable_source import read_document
from .project import ProjectError
from .project_lock import project_lock
from .safe_pull import fingerprint
from .sync_guard import binding_status, target
from .sync_plan import baseline_inventory, format_plan, plan_project, xml_inventory


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot_files(directory: Path) -> dict[str, Path]:
    manifest = json.loads((directory / "applications.json").read_text())
    if not isinstance(manifest, dict):
        raise ValueError("Invalid snapshot manifest")
    result = {}
    for app, filename in manifest.items():
        if (
            not isinstance(app, str)
            or not isinstance(filename, str)
            or not re.fullmatch(r"[0-9]+\.xml", filename)
        ):
            raise ValueError("Invalid snapshot entry")
        path = directory / filename
        if path.is_symlink():
            raise ValueError("Symlinked snapshot")
        result[app] = path
    return result


@dataclass(frozen=True)
class Snapshot:
    files: dict[str, Path]
    entities: tuple[Entity, ...] | None
    observer: Path


def load_snapshot(
    root: Path, installation_id: str, connection: OpenRoadConnection, scope: list[str]
) -> Snapshot | None:
    """Reject damaged/replaced/mismatched caches; callers fall back to full export."""
    try:
        pointer = json.loads((root / ".openroad/journal-snapshot.json").read_text())
        if (
            pointer["version"] != 3
            or pointer["installation_id"] != installation_id
            or pointer["target"] != target(connection)
            or pointer["scope"] != scope
            or not re.fullmatch(r"[0-9a-f]{32}", pointer["operation"])
        ):
            return None
        directory = (
            root / ".openroad/journal-snapshots" / pointer["operation"] / "reference"
        )
        if directory.is_symlink() or directory.parent.is_symlink():
            return None
        files = snapshot_files(directory)
        if set(files) != set(pointer["sha256"]):
            return None
        for app, path in files.items():
            if digest(path) != pointer["sha256"][app]:
                return None
            xml_inventory(read_document(path), app)
        ancestry = directory.parent / "ancestry.json"
        if ancestry.is_symlink() or digest(ancestry) != pointer["ancestry_sha256"]:
            return None
        observer = directory.parent / "observer.sqlite3"
        if observer.is_symlink() or digest(observer) != pointer["observer_sha256"]:
            return None
        return Snapshot(files, load_ancestry(ancestry), observer)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        etree.XMLSyntaxError,
        ProjectError,
    ):
        return None


def verify_selective_snapshot(
    connection: OpenRoadConnection,
    root: Path,
    limit: int = 100,
    *,
    rebootstrap: bool = False,
) -> dict[str, object]:
    """Publish full references with private observer progress, never reconciliation."""
    settings = require_odbc_settings(connection)
    if settings.database != connection.database:
        raise ProjectError("Snapshot SQL and ODBC database targets differ")
    with project_lock(root, "journal verify selective"):
        if binding_status(connection, root) != "verified":
            raise ProjectError(
                "Snapshot verification requires a verified target binding"
            )
        health = check_installation(settings)
        if health.issues or health.installation_id is None:
            raise ProjectError(
                "Snapshot verification requires a complete tracking inventory"
            )
        before = observe_journal(settings)
        if before.installation_id != health.installation_id:
            raise ProjectError("Tracking identity changed before snapshot observation")
        initial = fingerprint(root)
        _, tracked = baseline_inventory(root)
        scope = sorted(
            {a.casefold() for a in tracked}
            | {
                p.parent.name.casefold()
                for p in root.glob("*/app.json")
                if not p.parent.name.startswith(".")
            }
        )
        operation = root / ".openroad/journal-snapshots" / uuid4().hex
        operation.mkdir(parents=True)
        previous = (
            None
            if rebootstrap
            else load_snapshot(root, health.installation_id, connection, scope)
        )
        # Rebootstrap still resets the general consumer as explicitly requested.
        # Routine observations never read or modify that consumer.
        if rebootstrap:
            with acknowledgment_store(operation / "journal.sqlite3") as store:
                bind_store(store, health.installation_id)
                consumer_identity(store)
        observer_path = operation / "observer.sqlite3"
        observer_id = stage_observer(
            observer_path,
            health.installation_id,
            previous.observer if previous is not None else None,
        )
        with acknowledgment_store(observer_path) as store:
            batch = poll_journal(
                settings, store, limit, verify_complete=True, verify_receipts=True
            )
        if batch.installation_id != health.installation_id:
            raise ProjectError("Tracking identity changed during snapshot verification")
        mapping = map_applications(
            settings,
            batch,
            historical_entities=(previous.entities or ()) if previous else (),
        )
        reason = (
            "explicit_rebootstrap"
            if rebootstrap
            else "missing_or_invalid_snapshot"
            if previous is None
            else "event_batch_at_limit"
            if batch.complete is False
            or (batch.complete is None and len(batch.events) >= limit)
            else "unresolved_events"
            if mapping.full_comparison
            else ""
        )
        reuse: dict[str, Path] = {}
        if not reason and previous is not None:
            reuse = {
                app: path
                for app, path in previous.files.items()
                if app not in mapping.applications
            }
        selective_files: dict[str, Path] | None = None
        if not reason:
            plan_project(
                connection, root, capture_dir=operation / "selective", reuse_xml=reuse
            )
            selective_files = snapshot_files(operation / "selective")
        # Mandatory oracle: hook coverage and complete batch invalidation are not certified.
        changes = plan_project(connection, root, capture_dir=operation / "reference")
        reference = snapshot_files(operation / "reference")
        matched = None
        if selective_files is not None:
            matched = set(reference) == set(selective_files) and all(
                xml_inventory(read_document(reference[app]), app)
                == xml_inventory(read_document(selective_files[app]), app)
                for app in reference
            )
            if not matched:
                reason = "selective_snapshot_differs_from_full_reference"
        ancestry = read_ancestry(settings)
        write_ancestry(operation / "ancestry.json", ancestry)
        after = check_installation(settings)
        if (
            after.issues
            or after.installation_id != health.installation_id
            or fingerprint(root) != initial
        ):
            raise ProjectError(
                f"Project or installation changed; snapshot not published. Artifacts: {operation}"
            )
        report: dict[str, object] = {
            "installation_id": health.installation_id,
            "mapping": mapping.as_dict(),
            "mode": "full_fallback" if reason else "selective_verified",
            "fallback_reason": reason or None,
            "selective_matches_reference": matched,
            "reused_applications": sorted(set(reuse) & set(reference))
            if selective_files is not None
            else [],
            "full_reference_applications": sorted(reference),
            "selectively_exported_applications": (
                sorted(set(selective_files) - set(reuse))
                if selective_files is not None
                else []
            ),
            "changes": format_plan(changes),
            "acknowledged": False,
            "observer_consumer_id": observer_id,
            "observer_checkpointed_events": len(batch.events),
            "general_consumer_unchanged": not rebootstrap,
            "pending_set_complete": batch.complete,
            "incremental_ready": False,
            "journal_observation": before.as_dict(),
            "continuity_certified": False,
            "historical_entities_used": len(previous.entities or ()) if previous else 0,
            "captured_entities": len(ancestry) if ancestry is not None else None,
            "rebootstrapped": rebootstrap,
            "previous_state": str(operation / "previous") if rebootstrap else None,
        }
        checkpoint_observer(observer_path, batch.events)
        persist_comparison(operation, report)
        pointer = {
            "version": 3,
            "installation_id": health.installation_id,
            "target": target(connection),
            "scope": scope,
            "operation": operation.name,
            "sha256": {app: digest(path) for app, path in reference.items()},
            "ancestry_sha256": digest(operation / "ancestry.json"),
            "observer_sha256": digest(observer_path),
            "journal_observation": before.as_dict(),
        }
        destination = root / ".openroad/journal-snapshot.json"
        temporary = destination.with_name(f".journal-snapshot-{operation.name}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(pointer, stream)
                stream.flush()
                os.fsync(stream.fileno())
            if observe_journal(settings) != before:
                raise ProjectError(
                    f"Journal changed during observation; snapshot not published. Artifacts: {operation}"
                )
            if fingerprint(root) != initial:
                raise ProjectError("Project changed before snapshot publication")
            if rebootstrap:
                publish_consumer(root, operation)
            temporary.replace(destination)
            flush_directory(destination.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return {**report, "comparison": str(operation / "comparison.json")}

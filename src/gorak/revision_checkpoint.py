"""Whole-snapshot revision checkpoints; independent of journal receipts/retention.

Equal complete vectors reuse a snapshot. Opt-in bounded procedure decoding can
refresh dirty snapshots; unsupported or uncertified changes use full XML.
DBA generation rotation after restore/restart is mandatory.
"""

import hashlib
import json
import math
import re
import time
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from .connection import OpenRoadConnection, require_odbc_settings
from .errors import ProjectError
from .project_lock import project_lock
from .revision_check import check_revision_installation
from .revision_observation import BoundRevisionSample, observe_installed_revisions
from .sync_plan import Change, baseline_inventory, plan_project

CHECKPOINT_TTL = 900
MAX_CHECKPOINT_BYTES = 32 * 1024 * 1024


def scope_of(root: Path) -> list[str]:
    _, tracked = baseline_inventory(root)
    return sorted(
        {a.casefold() for a in tracked}
        | {
            p.parent.name.casefold()
            for p in root.glob("*/app.json")
            if not p.parent.name.startswith(".")
        }
    )


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def read_checkpoint(
    path: Path, binding: dict[str, object], now: float
) -> dict[str, str] | None:
    payload = read_checkpoint_payload(path, binding, now)
    return None if payload is None else payload["inventory"]


def read_checkpoint_payload(
    path: Path, binding: dict[str, object], now: float, *, changed: bool = False
) -> dict[str, Any] | None:
    try:
        if path.is_symlink():
            return None
        with path.open("rb") as stream:
            data = stream.read(MAX_CHECKPOINT_BYTES + 1)
        if len(data) > MAX_CHECKPOINT_BYTES:
            return None
        envelope = json.loads(data)
        payload = envelope["payload"]
        if hashlib.sha256(canonical(payload)).hexdigest() != envelope["sha256"]:
            return None
        expected = dict(binding)
        actual = dict(payload["binding"])
        if changed:
            expected.pop("sample", None)
            actual.pop("sample", None)
        if payload["version"] != 1 or actual != expected:
            return None
        created = payload["created"]
        if (
            type(created) not in (int, float)
            or not math.isfinite(created)
            or not 0 <= now - created < CHECKPOINT_TTL
        ):
            return None
        inventory = payload["inventory"]
        if not isinstance(inventory, dict) or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or not re.fullmatch(r"[0-9a-f]{64}", value)
            for key, value in inventory.items()
        ):
            return None
        return cast(dict[str, Any], payload)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def publish_checkpoint(
    path: Path,
    binding: dict[str, object],
    inventory: dict[str, str],
    now: float,
    source_snapshot: dict[str, Any] | None = None,
) -> None:
    payload = {"version": 1, "binding": binding, "created": now, "inventory": inventory}
    if source_snapshot is not None:
        payload["source_snapshot"] = source_snapshot
    data = canonical(
        {"payload": payload, "sha256": hashlib.sha256(canonical(payload)).hexdigest()}
    )
    if len(data) > MAX_CHECKPOINT_BYTES:
        return  # No partial checkpoint. Full comparisons remain available.
    atomic_write(path, data)


def atomic_write(path: Path, data: bytes) -> None:
    from .journal_reconcile import flush_directory

    temporary = path.with_name(".revision-" + uuid4().hex + ".json")
    try:
        import os

        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        flush_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def checkpoint_binding(
    connection: OpenRoadConnection, scope: list[str], sample: BoundRevisionSample
) -> dict[str, object]:
    from .sync_guard import target

    settings = require_odbc_settings(connection)
    endpoint = {
        key: value for key, value in asdict(settings).items() if key != "password"
    }
    # Canonical JSON shape avoids tuple/list differences after reading disk.
    result: dict[str, object] = json.loads(
        canonical(
            {
                "target": target(connection),
                "odbc_endpoint": endpoint,
                "scope": scope,
                "sample": asdict(sample),
                "configured_generation": connection.revision_generation,
                "source_decoding": connection.source_decoding,
            }
        )
    )
    return result


def revision_plan(
    connection: OpenRoadConnection,
    root: Path,
    *,
    verify_reference: bool = False,
    lock_held: bool = False,
) -> tuple[list[Change], dict[str, Any]]:
    """Return a fast quiet comparison or a fully revalidated fresh snapshot.

    Quiet reuse has no journal query, acknowledgment or consumer registration.
    Opt-in dirty decoding uses an event range certified by revision insert counts.
    An expired/offline/old checkout performs a new full snapshot. The DBA
    must rotate generation after restore, restart, hook changes or counter maintenance.
    """
    from .affected_source import select_affected
    from .encoded_source import UnsupportedSource
    from .procedure_snapshot import bootstrap_procedures, refresh_procedures
    from .revision_observation import RevisionSample
    from .sync_guard import binding_status

    if not connection.revision_generation:
        return plan_project(connection, root), {
            "mode": "full",
            "reason": "not_configured",
        }
    settings = require_odbc_settings(connection)
    if settings.database != connection.database:
        raise ProjectError("Revision SQL and source database targets differ")
    with nullcontext() if lock_held else project_lock(root, "revision comparison"):
        quarantine = root / ".openroad/revision-quarantine.json"
        if quarantine.exists():
            try:
                blocked = json.loads(quarantine.read_text())["generation"]
                if (
                    not isinstance(blocked, str)
                    or not UUID(blocked).int
                    or str(UUID(blocked)) != blocked
                ):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise ProjectError(
                    "Invalid revision quarantine; inspect before continuing"
                ) from None
            if blocked == connection.revision_generation:
                raise ProjectError(
                    "Revision generation is quarantined after a verification failure; repair tracking and rotate the generation"
                )
        if binding_status(connection, root) != "verified":
            return plan_project(connection, root), {"mode": "full", "reason": "unbound"}
        health = check_revision_installation(settings)
        if health.issues:
            atomic_write(
                quarantine,
                canonical(
                    {
                        "generation": connection.revision_generation,
                        "reason": "installation_check_failed",
                    }
                ),
            )
        if health.issues or health.revision_id != connection.revision_generation:
            # Configured generation is an explicit writer contract: fail closed
            # rather than running managed writes against a replaced installation.
            raise ProjectError(
                "Revision installation or configured generation is invalid; run gorak install --check-revision"
            )
        before = observe_installed_revisions(settings)
        if (
            before.revision_id != health.revision_id
            or before.parent_installation_id != health.parent_installation_id
        ):
            raise ProjectError("Revision generation changed during validation")
        scope = scope_of(root)
        binding = checkpoint_binding(connection, scope, before)
        path = root / ".openroad/revision-checkpoint.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        cached = read_checkpoint(path, binding, now) if before.sample.complete else None
        source_snapshot = None
        decoded = False
        history_queries = 0
        fallback = None
        created = now
        if cached is None and before.sample.complete and connection.source_decoding:
            previous = read_checkpoint_payload(path, binding, now, changed=True)
            if previous is not None and previous.get("source_snapshot") is not None:
                try:
                    raw = previous["binding"]["sample"]
                    prior_sample = BoundRevisionSample(
                        raw["revision_id"],
                        raw["parent_installation_id"],
                        RevisionSample(
                            tuple(tuple(row) for row in raw["sample"]["lanes"]),
                            raw["sample"]["scanned_rows"],
                        ),
                    )
                    selection = select_affected(
                        settings,
                        prior_sample,
                        before,
                        previous["source_snapshot"]["maximum"],
                    )
                    history_queries += selection.history_queries
                    cached, source_snapshot = refresh_procedures(
                        settings,
                        previous["source_snapshot"],
                        selection,
                        previous["inventory"],
                    )
                    # Dirty reuse never slides the full-oracle TTL.
                    created = previous["created"]
                    decoded = True
                except (UnsupportedSource, KeyError, TypeError, ValueError) as ex:
                    fallback = (
                        str(ex)
                        if isinstance(ex, UnsupportedSource)
                        else "invalid_source_checkpoint"
                    )
        sink: dict[str, str] = {}
        if cached is not None:
            changes = plan_project(connection, root, database_hashes=cached)
        else:
            changes = plan_project(connection, root, inventory_sink=sink)
            if connection.source_decoding and before.sample.complete:
                try:
                    history_queries += 1
                    source_snapshot = bootstrap_procedures(settings, scope, sink)
                except UnsupportedSource as ex:
                    fallback = str(ex)
        matched = None
        if verify_reference and cached is not None:
            reference = plan_project(connection, root, inventory_sink=sink)
            matched = cached == sink and changes == reference
            if not matched:
                path.unlink(missing_ok=True)
                atomic_write(
                    quarantine,
                    canonical(
                        {
                            "generation": connection.revision_generation,
                            "reason": "reference_mismatch",
                        }
                    ),
                )
                raise ProjectError(
                    "Revision checkpoint disagrees with full reference; checkpoint invalidated"
                )
        after = observe_installed_revisions(settings)
        after_health = check_revision_installation(settings)
        if after_health.issues:
            atomic_write(
                quarantine,
                canonical(
                    {
                        "generation": connection.revision_generation,
                        "reason": "installation_check_failed",
                    }
                ),
            )
        if before != after or health != after_health or scope_of(root) != scope:
            path.unlink(missing_ok=True)
            raise ProjectError(
                "Database changed during revision comparison; retry with a fresh snapshot"
            )
        if decoded:
            assert cached is not None
            publish_checkpoint(path, binding, cached, created, source_snapshot)
        elif cached is None and before.sample.complete:
            publish_checkpoint(path, binding, sink, now, source_snapshot)
        # Do not slide TTL on reuse: periodic full snapshots bound latent coverage risk.
        return changes, {
            "mode": "odbc_procedure_refresh"
            if decoded
            else "revision_reuse"
            if cached is not None
            else "full_refresh",
            "reason": None
            if cached is not None
            else fallback or "missing_expired_or_changed_checkpoint",
            "reference_matches": matched,
            "revision_lanes": before.sample.scanned_rows,
            "history_queries": history_queries,
            "full_reference_required": cached is None or verify_reference,
            "checkpoint_ttl_seconds": CHECKPOINT_TTL,
        }

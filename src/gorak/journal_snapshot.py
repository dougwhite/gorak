"""Verify selective observation refresh against fresh full XML exports."""

import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from lxml import etree

from .connection import OpenRoadConnection, require_odbc_settings
from .installation_check import check_installation
from .journal import acknowledgment_store, poll_journal
from .journal_mapping import map_applications
from .journal_reconcile import flush_directory, persist_comparison
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


def load_snapshot(
    root: Path, installation_id: str, connection: OpenRoadConnection, scope: list[str]
) -> dict[str, Path] | None:
    """Reject damaged/replaced/mismatched caches; callers fall back to full export."""
    try:
        pointer = json.loads((root / ".openroad/journal-snapshot.json").read_text())
        if (
            pointer["version"] != 1
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
        return files
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
    connection: OpenRoadConnection, root: Path, limit: int = 100
) -> dict[str, object]:
    """Publish only full-reference snapshots; never acknowledge newly polled events."""
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
        previous = load_snapshot(root, health.installation_id, connection, scope)
        with acknowledgment_store(root / ".openroad/journal.sqlite3") as store:
            batch = poll_journal(settings, store, limit)
        if batch.installation_id != health.installation_id:
            raise ProjectError("Tracking identity changed during snapshot verification")
        mapping = map_applications(settings, batch)
        operation = root / ".openroad/journal-snapshots" / uuid4().hex
        operation.mkdir(parents=True)
        reason = (
            "missing_or_invalid_snapshot"
            if previous is None
            else "unresolved_events"
            if mapping.full_comparison
            else ""
        )
        reuse: dict[str, Path] = {}
        if not reason and previous is not None:
            reuse = {
                app: path
                for app, path in previous.items()
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
            "incremental_ready": False,
        }
        persist_comparison(operation, report)
        pointer = {
            "version": 1,
            "installation_id": health.installation_id,
            "target": target(connection),
            "scope": scope,
            "operation": operation.name,
            "sha256": {app: digest(path) for app, path in reference.items()},
        }
        destination = root / ".openroad/journal-snapshot.json"
        temporary = destination.with_name(f".journal-snapshot-{operation.name}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(pointer, stream)
                stream.flush()
                os.fsync(stream.fileno())
            if fingerprint(root) != initial:
                raise ProjectError("Project changed before snapshot publication")
            temporary.replace(destination)
            flush_directory(destination.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return {**report, "comparison": str(operation / "comparison.json")}

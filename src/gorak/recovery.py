"""Conservatively finish a push whose database result already matches disk."""

import json
from pathlib import Path
from uuid import uuid4

from .connection import OpenRoadConnection
from .export import backup_application_xml
from .importer import validate_name
from .project import ProjectError
from .project_lock import project_lock
from .safe_pull import apply_files, fingerprint
from .sync_guard import binding_status
from .sync_plan import baseline_inventory, plan_project


def recover_push(connection: OpenRoadConnection, root: Path) -> str:
    with project_lock(root, "recover push", recover_push=True):
        marker = root / ".openroad/push-pending.json"
        if not marker.is_file():
            raise ProjectError("No interrupted push to recover")
        if binding_status(connection, root, recover_push=True) != "verified":
            raise ProjectError("Push recovery requires a verified target binding")
        initial = fingerprint(root)
        marker_bytes = marker.read_bytes()
        plan = plan_project(connection, root)
        if any(c.action not in {"unchanged", "converged"} for c in plan):
            raise ProjectError(
                "Recovery stopped: disk and database differ. Reconcile source explicitly; recovery does not import or overwrite disk source."
            )
        operation = root / ".openroad/pushes" / f"recovery-{uuid4().hex}"
        operation.mkdir(parents=True)
        (operation / "previous-marker.json").write_bytes(marker_bytes)
        _, tracked = baseline_inventory(root)
        apps = tracked | {p.parent.name for p in root.glob("*/app.json")}
        for app in apps:
            validate_name(app)
        changes: dict[Path, bytes | None] = {}
        for app in sorted(apps):
            cache = root / ".openroad" / app
            for path in cache.glob("*.xml"):
                changes[path] = None
            if not (root / app / "app.json").is_file():
                continue
            exported = operation / f"{app}.xml"
            backup_application_xml(connection, app, exported)
            changes[cache / f"{app}.xml"] = exported.read_bytes()
        # Verify staged XML against disk, then repeat the live comparison before install.
        from .importer import signature
        from .portable_source import (
            read_document,
            restore_application,
            restore_component,
        )
        from .sync_plan import xml_inventory

        for app in sorted(apps):
            folder = root / app
            if not (folder / "app.json").is_file():
                continue
            actual = xml_inventory(
                read_document(operation / f"{app}.xml"), app.casefold()
            )
            expected = {app.casefold(): signature(restore_application(folder))}
            expected.update(
                {
                    f"{app}/{p.stem}".casefold(): signature(restore_component(p))
                    for p in folder.glob("*.w4gl")
                }
            )
            if actual != expected:
                raise ProjectError("Database changed during recovery; marker retained")
        if any(
            c.action not in {"unchanged", "converged"}
            for c in plan_project(connection, root)
        ):
            raise ProjectError("Database changed during recovery; marker retained")
        if fingerprint(root) != initial or marker.read_bytes() != marker_bytes:
            raise ProjectError("Project changed during recovery; marker retained")
        apply_files(root, changes, operation, initial)
        (operation / "verified").write_text(json.dumps({"recovered": True}))
        marker.unlink()
        return f"Push recovery verified; baselines refreshed. Artifacts: {operation}"

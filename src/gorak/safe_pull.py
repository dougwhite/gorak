"""Stage database-to-disk changes, revalidate snapshots, and retain recovery files."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from shutil import copy2
from uuid import uuid4

from .connection import OpenRoadConnection
from .export import (
    application_export_paths,
    backup_application_xml,
    export_application_to_paths,
    read_applications,
)
from .importer import signature
from .portable_source import read_document
from .project import GorakContext, ProjectError
from .sync import SyncResult
from .sync_guard import guard_sync
from .sync_plan import baseline_inventory


def fingerprint(root: Path) -> dict[str, str]:
    result = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts[0] in {".git", ".openroad"}:
            continue
        if path.is_symlink():
            raise ProjectError(
                f"Sync does not support symlinked project source: {relative}"
            )
        if path.is_file():
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (root / ".openroad").glob("*/*.xml"):
        if path.parent.name not in {"pulls", "pushes", "imports", "runs"}:
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    for name in ["sync-target.json", "tracked-applications.json"]:
        path = root / ".openroad" / name
        if path.exists():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def apply_files(
    root: Path,
    changes: dict[Path, bytes | None],
    recovery: Path,
    expected: dict[str, str] | None = None,
) -> None:
    """Keep before-images and roll back only files still matching our own writes."""
    originals = {path: path.read_bytes() if path.exists() else None for path in changes}
    if expected is not None:
        for path, content in originals.items():
            actual = (
                hashlib.sha256(content).hexdigest() if content is not None else None
            )
            if actual != expected.get(path.relative_to(root).as_posix()):
                raise ProjectError(f"File changed before pull installation: {path}")
    for path, content in originals.items():
        if content is not None:
            backup = recovery / "before" / path.relative_to(root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(content)
    journal = {
        str(path.relative_to(root)): "delete" if data is None else "write"
        for path, data in changes.items()
    }
    (recovery / "changes.json").write_text(json.dumps(journal, indent=2))
    applied = []
    try:
        for path, content in changes.items():
            if (path.read_bytes() if path.exists() else None) != originals[path]:
                raise ProjectError(f"File changed during pull: {path}")
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                staged = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
                try:
                    staged.write_bytes(content)
                    staged.replace(path)
                finally:
                    staged.unlink(missing_ok=True)
            applied.append(path)
    except Exception:
        for path in reversed(applied):
            if (path.read_bytes() if path.exists() else None) != changes[path]:
                continue  # Never overwrite a concurrent external edit during recovery.
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        raise


def sync_project(
    connection: OpenRoadConnection,
    context: GorakContext,
    progress: Callable[[str], None] | None = None,
) -> SyncResult:
    if context.project is None:
        raise ProjectError("Sync requires a gorak project")
    root = context.project.root
    directory = root / ".openroad/pulls"
    directory.mkdir(parents=True, exist_ok=True)
    lock = root / ".openroad/pull.lock"
    try:
        handle = lock.open("x")
    except FileExistsError as ex:
        raise ProjectError(f"Another pull may be active; inspect {lock}") from ex
    operation = directory / uuid4().hex
    try:
        with handle:
            handle.write(str(operation))
            handle.flush()
            before = fingerprint(root)
            plan = guard_sync(connection, root, push=False)
            # guard_sync can establish a binding only for a previously empty cache.
            if set(before) - fingerprint(root).keys():
                raise ProjectError("Project changed while planning pull")
            snapshot = fingerprint(root)
            if (set(snapshot) - set(before) - {".openroad/sync-target.json"}) or any(
                snapshot.get(key) != value for key, value in before.items()
            ):
                raise ProjectError("Project changed while planning pull")
            apps = {
                c.key.split("/")[0] for c in plan if c.action in {"pull", "converged"}
            }
            if not apps:
                return SyncResult(len(plan), 0, 0)
            operation.mkdir()
            stage = operation / "stage"
            stage.mkdir()
            baseline, tracked = baseline_inventory(root)
            names = {name.casefold(): name for name in tracked}
            names.update(
                {
                    p.parent.name.casefold(): p.parent.name
                    for p in root.glob("*/app.json")
                }
            )
            available = {
                a.name.casefold(): a.name for a in read_applications(connection)
            }
            staged_xml: dict[str, Path] = {}
            changes: dict[Path, bytes | None] = {}
            defaults = root / "field_defaults.json"
            if defaults.exists():
                copy2(defaults, stage / defaults.name)
            exported_count = 0
            for app in sorted(apps):
                name = names.get(app, available.get(app, app))
                if app in available and name != available[app]:
                    raise ProjectError(
                        f"Application casing changed; reconcile explicitly: {name}"
                    )
                known = [
                    key.split("/", 1)[1]
                    for key in baseline
                    if key.startswith(app + "/")
                ]
                old_files = {
                    root / name / "app.json",
                    root / name / "field_defaults.json",
                    root / name / ".gorak-source/application.xml",
                    root / name / ".gorak-source/format",
                }
                for component in known:
                    for path in (root / name).glob("*"):
                        if path.stem.casefold() == component and path.suffix in {
                            ".w4gl",
                            ".wml",
                        }:
                            old_files.add(path)
                    for path in (root / name / ".gorak-source/components").glob(
                        "*.xml"
                    ):
                        if path.stem.casefold() == component:
                            old_files.add(path)
                old_files.update((root / ".openroad" / name).glob("*.xml"))
                for path in old_files:
                    if path.is_file():
                        changes[path] = None
                if app not in available:
                    continue
                app_defaults = root / name / "field_defaults.json"
                if app_defaults.exists():
                    (stage / name).mkdir(parents=True, exist_ok=True)
                    copy2(app_defaults, stage / name / "field_defaults.json")
                paths = application_export_paths(stage, name)
                exported = export_application_to_paths(
                    connection, name, paths, progress
                )
                metadata = {
                    "starting_component": exported.application.start_component,
                    "description": exported.application.description,
                    "included_applications": exported.included_applications,
                }
                for key, value in [
                    ("database_name", exported.application.database_name),
                    ("database_type", exported.application.database_type),
                ]:
                    if value:
                        metadata[key] = value
                (stage / name / "app.json").write_text(
                    json.dumps(metadata, indent=4) + "\n"
                )
                staged_xml[app] = paths.xml_path
                exported_count += len(exported.components)
            # Re-scan database inventory and compare the exact XML staged for installation.
            latest = {a.name.casefold(): a.name for a in read_applications(connection)}
            for app in apps:
                if (app in available) != (app in latest):
                    raise ProjectError(
                        f"Database application changed during pull: {app}"
                    )
                if app in staged_xml:
                    check = operation / f"{app}-verify.xml"
                    backup_application_xml(connection, latest[app], check)
                    if signature(read_document(check)) != signature(
                        read_document(staged_xml[app])
                    ):
                        raise ProjectError(
                            f"Database source changed during pull: {app}"
                        )
            if fingerprint(root) != snapshot:
                raise ProjectError(
                    "Local project changed during pull; source was not installed"
                )
            for path in stage.rglob("*"):
                if path.is_file():
                    destination = root / path.relative_to(stage)
                    if (
                        destination.exists()
                        and destination not in changes
                        and destination != root / "field_defaults.json"
                        and destination.read_bytes() != path.read_bytes()
                    ):
                        raise ProjectError(
                            f"Pull would overwrite an untracked source file: {destination}"
                        )
                    changes[destination] = path.read_bytes()
            # Keep removed apps discoverable so a later re-addition is visible to status.
            changes[root / ".openroad/tracked-applications.json"] = (
                json.dumps(sorted(tracked | set(names.values())), indent=2) + "\n"
            ).encode()
            changes = {
                p: data
                for p, data in changes.items()
                if (p.read_bytes() if p.exists() else None) != data
            }
            pending = root / ".openroad/pull-pending.json"
            pending.write_text(json.dumps({"operation": str(operation)}))
            apply_files(root, changes, operation, snapshot)
            (operation / "verified").write_text(
                "Pull installed after disk and database revalidation\n"
            )
            pending.unlink()
            if progress:
                progress(f"Pull recovery artifacts: {operation}")
            return SyncResult(
                len(plan), sum(c.action != "unchanged" for c in plan), exported_count
            )
    except Exception as ex:
        raise ProjectError(f"{ex}\nPull artifacts: {operation}") from ex
    finally:
        lock.unlink()

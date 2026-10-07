"""Stage database-to-disk changes, revalidate snapshots, and retain recovery files."""

import hashlib
import json
from collections.abc import Callable
from contextlib import nullcontext
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
from .export_failures import (
    ExportFailure,
    cached_components,
    failed_source,
    finalize_baseline,
)
from .export_pipeline import prefetched_exports
from .importer import signature
from .portable_source import read_document
from .project import GorakContext, ProjectError
from .project_lock import project_lock
from .sync import SyncResult
from .sync_guard import guard_sync
from .sync_plan import Change, baseline_inventory


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
    for path in (root / ".openroad").glob("*/*"):
        if not path.is_file() or not (
            path.suffix == ".xml" or path.name.endswith(".receipt.json")
        ):
            continue
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
    if expected is not None and fingerprint(root) != expected:
        raise ProjectError("File changed before pull installation; retry")
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
    *,
    lock_held: bool = False,
) -> SyncResult:
    if context.project is None:
        raise ProjectError("Sync requires a gorak project")
    root = context.project.root
    # CLI callers already own the mutation lock. Direct callers must acquire it
    # before creating pull.lock, so revision planning never reacquires either lock.
    with nullcontext() if lock_held else project_lock(root, "sync pull"):
        return _sync_project(connection, root, progress)


def _sync_project(
    connection: OpenRoadConnection,
    root: Path,
    progress: Callable[[str], None] | None,
    *,
    take_database: bool = False,
) -> SyncResult:
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
            if take_database:
                from .sync_plan import plan_project

                plan = plan_project(connection, root)
            else:
                plan = guard_sync(connection, root, push=False, lock_held=True)
            # guard_sync can establish a binding only for a previously empty cache.
            if set(before) - fingerprint(root).keys():
                raise ProjectError("Project changed while planning pull")
            snapshot = fingerprint(root)
            if (set(snapshot) - set(before) - {".openroad/sync-target.json"}) or any(
                snapshot.get(key) != value for key, value in before.items()
            ):
                raise ProjectError("Project changed while planning pull")
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
            # backupapp may omit a broken catalog component altogether. Missing
            # successful baselines must remain pending even when XML is unchanged.
            from .export import read_components

            planned = {change.key for change in plan}
            for app in sorted(names.keys() & available.keys()):
                for catalog_component in read_components(connection, available[app]):
                    key = f"{app}/{catalog_component.name}".casefold()
                    if key not in baseline and key not in planned:
                        plan.append(Change(key, "pull", "unchanged", "added"))
                        planned.add(key)
            apps = {
                c.key.split("/")[0] for c in plan if c.action in {"pull", "converged"}
            }
            if take_database:
                apps |= set(names)
            if not apps:
                return SyncResult(len(plan), 0, 0)
            operation.mkdir()
            stage = operation / "stage"
            stage.mkdir()
            staged_xml: dict[str, Path] = {}
            changes: dict[Path, bytes | None] = {}
            defaults = root / "field_defaults.json"
            if defaults.exists():
                copy2(defaults, stage / defaults.name)
            from .image_assets import source_files

            for asset in source_files(root):
                target = stage / asset.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                copy2(asset, target)
            exported_count = 0
            failures: list[ExportFailure] = []
            app_failures: dict[str, list[ExportFailure]] = {}
            with prefetched_exports(
                [available[app] for app in sorted(apps) if app in available],
                connection.export_workers,
                lambda app, path: backup_application_xml(connection, app, path),
            ) as prefetched:
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
                        old_files.update(
                            path
                            for path in (root / name).glob("*.fielddefaults.json")
                            if path.name.removesuffix(".fielddefaults.json").casefold()
                            == component
                        )
                        old_files.update(
                            path
                            for path in (root / name).glob("*.queries.json")
                            if path.name.removesuffix(".queries.json").casefold()
                            == component
                        )
                        old_files.update(
                            path
                            for path in (root / name).glob("*.icons.json")
                            if path.name.removesuffix(".icons.json").casefold()
                            == component
                        )
                        for path in (root / name / ".gorak-source/components").glob(
                            "*.xml"
                        ):
                            if path.stem.casefold() == component:
                                old_files.add(path)
                    if take_database:
                        old_files.update((root / name).glob("*.w4gl"))
                        old_files.update((root / name).glob("*.wml"))
                        old_files.update((root / name).glob("*.fielddefaults.json"))
                        old_files.update((root / name).glob("*.queries.json"))
                        old_files.update((root / name).glob("*.icons.json"))
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
                    # Seed assets for stable name allocation; never prune shared files.
                    from .image_assets import source_files

                    for asset in source_files(root / name):
                        if "images" not in asset.relative_to(root / name).parts:
                            continue
                        target = stage / name / asset.relative_to(root / name)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        copy2(asset, target)
                    paths = application_export_paths(stage, name)
                    _, native_xml = next(prefetched)
                    exported = export_application_to_paths(
                        connection,
                        name,
                        paths,
                        progress,
                        asset_origins=root / name,
                        native_xml=native_xml,
                    )
                    failures.extend(exported.failures)
                    app_failures[app] = exported.failures
                    for path in old_files:
                        if (
                            path != root / ".openroad" / name / f"{name}.xml"
                            and failed_source(path, exported.failures)
                        ):
                            changes.pop(path, None)
                    staged_xml[app] = paths.xml_path
                    exported_count += len(exported.components)
            # Re-scan database inventory and compare the exact XML staged for installation.
            latest = {a.name.casefold(): a.name for a in read_applications(connection)}
            for app in apps:
                if (app in available) != (app in latest):
                    raise ProjectError(
                        f"Database application changed during pull: {app}"
                    )
            with prefetched_exports(
                sorted(staged_xml),
                connection.export_workers,
                lambda app, path: backup_application_xml(connection, latest[app], path),
            ) as verification:
                for app, native_xml in verification:
                    check = operation / f"{app}-verify.xml"
                    copy2(native_xml, check)
                    if signature(read_document(check)) != signature(
                        read_document(staged_xml[app])
                    ):
                        raise ProjectError(
                            f"Database source changed during pull: {app}"
                        )
            for app, xml_path in staged_xml.items():
                finalize_baseline(
                    xml_path,
                    app_failures[app],
                    cached_components(
                        root / ".openroad" / xml_path.parent.name,
                        {f.component.casefold() for f in app_failures[app]},
                    )
                    if app_failures[app]
                    else {},
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
                len(plan),
                sum(c.action != "unchanged" for c in plan),
                exported_count,
                failures,
            )
    except Exception as ex:
        raise ProjectError(f"{ex}\nPull artifacts: {operation}") from ex
    finally:
        lock.unlink()

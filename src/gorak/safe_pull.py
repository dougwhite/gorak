"""Stage database-to-disk changes, revalidate snapshots, and retain recovery files."""

import hashlib
import json
import os
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
from uuid import uuid4

from lxml import etree

from . import comparison_cache
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
from .operation_progress import report
from .portable_source import cached_source_scope, read_document
from .project import GorakContext, ProjectError
from .project_lock import project_lock
from .sync import SyncResult
from .sync_guard import guard_sync
from .sync_plan import Change, baseline_inventory, source_input_key


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def same_xml(first: Path, second: Path) -> bool:
    # Staging has already parsed the exported XML. Identical bytes need no second
    # tree comparison; differing serialization still uses the complete comparison.
    return file_digest(first) == file_digest(second) or signature(
        read_document(first)
    ) == signature(read_document(second))


def matching_native_inventory(
    path: Path, app: str, expected: set[str], catalog: set[str]
) -> int | None:
    """Validate complete captured XML before adopting it without source conversion."""
    from .source_xml import application_children

    keys: set[str] = set()
    for node in application_children(path):
        if node.tag == "APPLICATION":
            key = app
        else:
            name = node.get("name")
            if not name:
                raise ProjectError("Missing or duplicate exported component names")
            key = f"{app}/{name}".casefold()
        if key in keys:
            raise ProjectError("Missing or duplicate exported component names")
        keys.add(key)
    if app not in keys:
        raise ProjectError("Expected one exported application")
    if keys != expected or not catalog.issubset(keys):
        return None
    return len(keys) - 1


def component_source_files(folder: Path, names: set[str]) -> set[Path]:
    """Select only known component files, leaving shared assets and notes alone."""
    files: set[Path] = set()
    if not names:
        return files
    for path in folder.glob("*"):
        for suffix in (
            ".w4gl",
            ".wml",
            ".fielddefaults.json",
            ".queries.json",
            ".icons.json",
        ):
            if (
                path.name.endswith(suffix)
                and path.name.removesuffix(suffix).casefold() in names
            ):
                files.add(path)
                break
    files.update(
        path
        for path in (folder / ".gorak-source/components").glob("*.xml")
        if path.stem.casefold() in names
    )
    return files


def fingerprint(root: Path) -> dict[str, str]:
    result = {}
    for directory, directories, files in os.walk(root):
        folder = Path(directory)
        if folder == root:
            directories[:] = [
                name for name in directories if name not in {".git", ".openroad"}
            ]
            files = [name for name in files if name not in {".git", ".openroad"}]
        for name in directories + files:
            path = folder / name
            relative = path.relative_to(root)
            if path.is_symlink():
                raise ProjectError(
                    f"Sync does not support symlinked project source: {relative}"
                )
            if path.is_file():
                result[relative.as_posix()] = file_digest(path)
    for path in (root / ".openroad").glob("*/*"):
        if not path.is_file() or not (
            path.suffix == ".xml" or path.name.endswith(".receipt.json")
        ):
            continue
        if path.parent.name not in {"pulls", "pushes", "imports", "runs"}:
            result[path.relative_to(root).as_posix()] = file_digest(path)
    for name in ["sync-target.json", "tracked-applications.json"]:
        path = root / ".openroad" / name
        if path.exists():
            result[path.relative_to(root).as_posix()] = file_digest(path)
    return result


def prime_matching_baseline(
    root: Path,
    snapshot: dict[str, str],
    changes: dict[Path, bytes | None],
    plan: list[Change],
) -> bool:
    """Retain proven source equality only if the installed bytes still match it."""
    if any(
        change.action not in {"unchanged", "converged"}
        or change.reason
        or change.disk == "invalid"
        for change in plan
    ) or any(path.relative_to(root).parts[0] != ".openroad" for path in changes):
        return False
    expected = dict(snapshot)
    for path, content in changes.items():
        key = path.relative_to(root).as_posix()
        if content is None:
            expected.pop(key, None)
        else:
            expected[key] = hashlib.sha256(content).hexdigest()
    expected_keys = {
        change.key
        for change in plan
        if change.disk != "deleted" and change.database != "deleted"
    }
    baseline_paths: dict[str, list[Path]] = {}
    for name in expected:
        relative = Path(name)
        if (
            len(relative.parts) == 3
            and relative.parts[0] == ".openroad"
            and relative.suffix == ".xml"
        ):
            baseline_paths.setdefault(relative.parts[1].casefold(), []).append(
                root / relative
            )
    # This shortcut need not prove historical overlay precedence. A single
    # full baseline per application has no mtime-dependent source selection.
    if any(len(paths) != 1 for paths in baseline_paths.values()):
        return False
    try:
        report("Recording verified local comparison")
        if fingerprint(root) != expected:
            return False
        key = comparison_cache.project_key(root, verified_digests=expected)
        # Planning's parsed baseline index must not supply superseded XML.
        raw_baseline: dict[str, str] = {}
        with cached_source_scope():
            baseline, apps = baseline_inventory(
                root, raw_sink=raw_baseline, expected_digests=expected
            )
        if set(baseline) != expected_keys:
            return False
        if any(app not in baseline for app in baseline_paths):
            return False
        component_caches: list[tuple[str, str, dict[str, object]]] = []
        source_keys: set[str] = set()
        for manifest in sorted(root.glob("*/app.json")):
            folder = manifest.parent
            if folder.name.startswith("."):
                continue
            dependency = comparison_cache.shared_key(
                root, folder, verified_digests=expected
            )
            records: dict[str, object] = {}
            for source in [manifest, *sorted(folder.glob("*.w4gl"))]:
                application = source == manifest
                source_key = (
                    folder.name if application else f"{folder.name}/{source.stem}"
                ).casefold()
                if source_key not in baseline or source_key not in raw_baseline:
                    return False
                source_keys.add(source_key)
                records[source.name] = {
                    "input": source_input_key(
                        root,
                        source,
                        application=application,
                        baseline_raw=raw_baseline[source_key],
                        verified_digests=expected,
                    ),
                    "signature": baseline[source_key],
                }
            component_caches.append(
                ("components:" + str(folder.resolve()), dependency, records)
            )
        if source_keys != expected_keys:
            return False
        if fingerprint(root) != expected or comparison_cache.project_key(root) != key:
            return False
        for scope, dependency, records in component_caches:
            comparison_cache.save(scope, dependency, records)
        comparison_cache.save(
            "local:" + str(root.resolve()),
            key,
            {"baseline": baseline, "disk": baseline, "apps": sorted(apps)},
        )
        return True
    except (OSError, ValueError, ProjectError, etree.XMLSyntaxError):
        # Comparison metadata is disposable; a concurrent edit must not be
        # certified or turn a completed source installation into a failed pull.
        return False


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


@comparison_cache.project_cached
@comparison_cache.scope()
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
        with handle, TemporaryDirectory(prefix="gorak-sync-") as temporary:
            handle.write(str(operation))
            handle.flush()
            capture_dir = Path(temporary) / "planning"
            report("Checking local files before pull")
            before = fingerprint(root)
            if take_database:
                from .sync_plan import plan_project

                plan = plan_project(connection, root, capture_dir=capture_dir)
            else:
                plan = guard_sync(
                    connection,
                    root,
                    push=False,
                    lock_held=True,
                    capture_dir=capture_dir,
                )
            # guard_sync can establish a binding only for a previously empty cache.
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
            report("Listing database applications for pull")
            available = {
                a.name.casefold(): a.name for a in read_applications(connection)
            }
            # backupapp may omit a broken catalog component altogether. Missing
            # successful baselines must remain pending even when XML is unchanged.
            from .export import read_components

            planned = {change.key for change in plan}
            catalogs: dict[str, set[str]] = {}
            report("Checking database component catalogs")
            for app in sorted(names.keys() & available.keys()):
                catalog = catalogs[app] = set()
                for catalog_component in read_components(connection, available[app]):
                    key = f"{app}/{catalog_component.name}".casefold()
                    catalog.add(key)
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
            shared_assets_staged = False
            exported_count = 0
            failures: list[ExportFailure] = []
            app_failures: dict[str, list[ExportFailure]] = {}
            adopted_apps: set[str] = set()
            captures = capture_dir / "applications.json"
            captured_xml = (
                {
                    app: capture_dir / filename
                    for app, filename in json.loads(captures.read_text()).items()
                }
                if captures.exists()
                else {}
            )
            app_plans: dict[str, list[Change]] = {}
            for change in plan:
                app_plans.setdefault(change.key.split("/", 1)[0], []).append(change)
            baseline_only = {
                app: {change.key for change in app_plan if change.database != "deleted"}
                for app, app_plan in app_plans.items()
                if not take_database
                and app in captured_xml
                and any(change.key == app for change in app_plan)
                and all(
                    change.action in {"unchanged", "converged"}
                    and not change.reason
                    and change.disk != "invalid"
                    for change in app_plan
                )
            }
            matching_sources = {
                change.key
                for change in plan
                if not take_database
                and change.key.split("/", 1)[0] in captured_xml
                and change.action in {"unchanged", "converged"}
                and not change.reason
                and change.disk not in {"invalid", "deleted"}
                and change.database != "deleted"
            }

            def preserve_source(path: Path) -> bool:
                relative = path.relative_to(root)
                if len(relative.parts) != 2:
                    return False
                app, filename = relative.parts
                if filename == "app.json":
                    return app.casefold() in matching_sources
                for suffix in (
                    ".w4gl",
                    ".wml",
                    ".fielddefaults.json",
                    ".queries.json",
                    ".icons.json",
                ):
                    if filename.endswith(suffix):
                        key = f"{app}/{filename.removesuffix(suffix)}".casefold()
                        return key in matching_sources
                return False

            def stage_export(app: str, path: Path) -> None:
                planned_xml = captured_xml.get(app.casefold())
                if planned_xml is None:
                    backup_application_xml(connection, app, path)
                else:
                    copy2(planned_xml, path)

            report("Exporting pull applications", 0, len(apps))
            with prefetched_exports(
                [available[app] for app in sorted(apps) if app in available],
                connection.export_workers,
                stage_export,
            ) as prefetched:
                for app_index, app in enumerate(sorted(apps), 1):
                    report("Exporting pull applications", app_index - 1, len(apps))
                    name = names.get(app, available.get(app, app))
                    if app in available and name != available[app]:
                        raise ProjectError(
                            f"Application casing changed; reconcile explicitly: {name}"
                        )
                    native_xml = None
                    if app in available:
                        _, native_xml = next(prefetched)
                    if native_xml is not None and app in baseline_only:
                        # Normal conversion checks the catalog again. Retain that
                        # freshness even when matching source needs no projection.
                        catalog = catalogs.setdefault(app, set())
                        catalog.update(
                            f"{app}/{component.name}".casefold()
                            for component in read_components(connection, name)
                        )
                        component_count = matching_native_inventory(
                            native_xml,
                            app,
                            baseline_only[app],
                            catalog,
                        )
                        if component_count is not None:
                            report(f"Establishing baseline for matching source: {name}")
                            paths = application_export_paths(stage, name)
                            paths.xml_path.parent.mkdir(parents=True, exist_ok=True)
                            copy2(native_xml, paths.xml_path)
                            deleted = {
                                change.key.split("/", 1)[1]
                                for change in app_plans[app]
                                if change.key != app
                                and change.key in baseline
                                and change.action == "converged"
                                and change.disk == change.database == "deleted"
                            }
                            for path in component_source_files(root / name, deleted):
                                if path.is_file():
                                    changes[path] = None
                            for old_xml in (root / ".openroad" / name).glob("*.xml"):
                                changes[old_xml] = None
                            staged_xml[app] = paths.xml_path
                            app_failures[app] = []
                            adopted_apps.add(app)
                            exported_count += component_count
                            report("Exporting pull applications", app_index, len(apps))
                            continue
                    known = {
                        key.split("/", 1)[1]
                        for key in baseline
                        if key.startswith(app + "/")
                    }
                    old_files = {
                        root / name / "app.json",
                        root / name / "field_defaults.json",
                        root / name / ".gorak-source/application.xml",
                        root / name / ".gorak-source/format",
                    }
                    old_files.update(component_source_files(root / name, known))
                    if take_database:
                        old_files.update((root / name).glob("*.w4gl"))
                        old_files.update((root / name).glob("*.wml"))
                        old_files.update((root / name).glob("*.fielddefaults.json"))
                        old_files.update((root / name).glob("*.queries.json"))
                        old_files.update((root / name).glob("*.icons.json"))
                    old_files.update((root / ".openroad" / name).glob("*.xml"))
                    for path in old_files:
                        if path.is_file() and not preserve_source(path):
                            changes[path] = None
                    if app not in available:
                        continue
                    assert native_xml is not None
                    from .image_assets import source_files

                    if not shared_assets_staged:
                        defaults = root / "field_defaults.json"
                        if defaults.exists():
                            copy2(defaults, stage / defaults.name)
                        for asset in source_files(root):
                            target = stage / asset.relative_to(root)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            copy2(asset, target)
                        shared_assets_staged = True
                    app_defaults = root / name / "field_defaults.json"
                    if app_defaults.exists():
                        (stage / name).mkdir(parents=True, exist_ok=True)
                        copy2(app_defaults, stage / name / "field_defaults.json")
                    # Seed assets for stable name allocation; never prune shared files.
                    for asset in source_files(root / name):
                        if "images" not in asset.relative_to(root / name).parts:
                            continue
                        target = stage / name / asset.relative_to(root / name)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        copy2(asset, target)
                    paths = application_export_paths(stage, name)
                    report(f"Converting pull source: {name}")
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
                    report("Exporting pull applications", app_index, len(apps))
            # Re-scan database inventory and compare the exact XML staged for installation.
            report("Rechecking database applications before installation")
            latest = {a.name.casefold(): a.name for a in read_applications(connection)}
            for app in apps:
                if (app in available) != (app in latest):
                    raise ProjectError(
                        f"Database application changed during pull: {app}"
                    )
            report("Verifying pull applications", 0, len(staged_xml))
            with prefetched_exports(
                sorted(staged_xml),
                connection.export_workers,
                lambda app, path: backup_application_xml(connection, latest[app], path),
            ) as verification:
                for verify_index, (app, native_xml) in enumerate(verification, 1):
                    check = operation / f"{app}-verify.xml"
                    copy2(native_xml, check)
                    if not same_xml(check, staged_xml[app]):
                        raise ProjectError(
                            f"Database source changed during pull: {app}"
                        )
                    report("Verifying pull applications", verify_index, len(staged_xml))
            report("Preparing verified source for installation")
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
                    # A catalog omission can require normal projection even when
                    # other source already matches this captured native export.
                    # Keep those proven source bytes, including CRLF and comments.
                    if preserve_source(destination):
                        continue
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
            report("Installing verified source files")
            apply_files(root, changes, operation, snapshot)
            report("Source installation", 1, 1)
            (operation / "verified").write_text(
                "Pull installed after disk and database revalidation\n"
            )
            pending.unlink()
            if not take_database and not failures and apps <= adopted_apps:
                prime_matching_baseline(root, snapshot, changes, plan)
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

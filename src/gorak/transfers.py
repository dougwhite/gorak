"""Sender-authoritative incremental transfers with a small successful-transfer ledger."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
import tomllib
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from lxml import etree

from .connection import OpenRoadConnection
from .export import (
    application_metadata,
    backup_application_xml,
    project_component_files,
)
from .image_assets import AssetWriter, externalize
from .import_backend import delete_database_source, import_component_xml
from .importer import validate_name
from .native_styles import parent_styles, resolution_scope, validation_scope
from .operation_progress import report
from .parser import NS, parse_application_xml
from .project import ProjectError
from .source_output import write_text
from .source_reads import captured as captured_reads
from .source_xml import MAX_DOCUMENT_BYTES, application_children
from .transfer_catalog import inventory as inventory
from .xml_writer import document, new_application, new_component, prepare_submission

SUFFIXES = (".w4gl", ".wml", ".fielddefaults.json", ".queries.json", ".icons.json")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def combined(values: dict[str, str]) -> str:
    return digest(json.dumps(values, sort_keys=True).encode())


def source_files(root: Path, app: str) -> list[Path]:
    from .image_assets import source_files as assets

    folder = root / app
    return sorted(
        {
            *[p for suffix in SUFFIXES for p in folder.glob("*" + suffix)],
            *[
                p
                for p in (
                    folder / "app.json",
                    folder / "field_defaults.json",
                    root / "field_defaults.json",
                )
                if p.is_file()
            ],
            *assets(folder),
            *assets(root),
        }
    )


def check_paths(root: Path) -> None:
    """Check filesystem boundaries once, without reading file contents."""
    pending = [root]
    while pending:
        folder = pending.pop()
        if folder.is_symlink() or folder.is_junction():
            raise ProjectError(f"Symlinked project source is unsupported: {folder}")
        with os.scandir(folder) as entries:
            for entry in entries:
                if folder == root and entry.name == ".git":
                    continue
                path = Path(entry.path)
                if entry.is_symlink() or (
                    entry.is_dir(follow_symlinks=False) and path.is_junction()
                ):
                    raise ProjectError(
                        f"Symlinked project source is unsupported: {path}"
                    )
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)


def image_dependencies(path: Path, data: bytes) -> set[Path]:
    # Only parse documents that can contain an external asset reference.
    if b"images" not in data and b"\\" not in data and b"&" not in data:
        return set()
    found: set[Path] = set()

    def reference(value: Any) -> None:
        if isinstance(value, dict):
            value = value.get("src")
        if isinstance(value, str) and value.startswith("images/"):
            from .image_assets import asset_path

            found.add(asset_path(path.parent, value))

    def stylesheet(value: Any) -> None:
        if isinstance(value, dict):
            if "src" in value:
                reference(value)
            else:
                for child in value.values():
                    stylesheet(child)
        elif isinstance(value, list):
            for child in value:
                stylesheet(child)

    try:
        if path.suffix == ".wml":
            from .source_xml import from_bytes

            for node in from_bytes(data).iter():
                reference(node.get("src"))
        elif path.suffix == ".w4gl":
            from .component_edits import SUPPORTED_TYPES
            from .parser import split_w4gl

            metadata = tomllib.loads(split_w4gl(data.decode("utf-8"))[0])
            for kind in SUPPORTED_TYPES:
                fields = metadata.get(kind)
                if isinstance(fields, dict):
                    reference(fields.get("windowicon"))
            icons = metadata.get("icons")
            if isinstance(icons, dict) and isinstance(icons.get("entries"), list):
                for entry in icons["entries"]:
                    reference(entry)
        elif path.name == "app.json":
            value = json.loads(data)
            if isinstance(value, dict):
                reference(value.get("window_icon"))
        elif path.name == "field_defaults.json" or path.name.endswith(
            ".fielddefaults.json"
        ):
            stylesheet(json.loads(data))
    except (ValueError, etree.XMLSyntaxError):
        pass  # Reconstruction reports invalid source; it cannot be checkpointed.
    return found


def hashes(
    root: Path,
    apps: list[str] | None = None,
    *,
    captured: dict[Path, str] | None = None,
    inputs: dict[Path, bytes] | None = None,
    dependency_cache: dict[str, Any] | None = None,
) -> dict[str, str]:
    apps = (
        apps
        if apps is not None
        else sorted(
            p.parent.name
            for p in root.glob("*/app.json")
            if not p.parent.name.startswith(".")
        )
    )
    result: dict[str, str] = {}
    read: dict[Path, str] = {} if captured is None else dict(captured)
    for index, app in enumerate(apps, 1):
        validate_name(app)
        folder = root / app
        paths = source_files(root, app) if inputs is None else sorted(inputs)
        values: dict[Path, str] = {}
        dependencies: dict[Path, set[Path]] = {}
        has_images = any("images" in p.relative_to(root).parts for p in paths)
        for path in paths:
            if path not in read:
                data = path.read_bytes() if inputs is None else inputs[path]
                read[path] = digest(data)
            elif has_images and path.suffix in {".w4gl", ".wml", ".json"}:
                data = path.read_bytes() if inputs is None else inputs[path]
            else:
                data = b""
            values[path] = read[path]
            if path.suffix in {".w4gl", ".wml", ".json"}:
                relative = path.relative_to(root).as_posix()
                cached = (dependency_cache or {}).get(relative)
                if (
                    isinstance(cached, dict)
                    and cached.get("version") == 3
                    and cached.get("hash") == values[path]
                    and isinstance(cached.get("paths"), list)
                    and all(
                        isinstance(item, str)
                        and not Path(item).is_absolute()
                        and ".." not in Path(item).parts
                        for item in cached["paths"]
                    )
                ):
                    dependencies[path] = {root / item for item in cached["paths"]}
                else:
                    dependencies[path] = image_dependencies(path, data)
                    if dependency_cache is not None:
                        dependency_cache[relative] = {
                            "version": 3,
                            "hash": values[path],
                            "paths": sorted(
                                p.relative_to(root).as_posix()
                                for p in dependencies[path]
                            ),
                        }

        def fingerprint(
            paths: list[Path],
            values: dict[Path, str] = values,
            dependencies: dict[Path, set[Path]] = dependencies,
        ) -> str:
            selected = {path for path in paths if path in values}
            for path in list(selected):
                selected.update(dependencies.get(path, set()))
            return combined(
                {
                    path.relative_to(root).as_posix(): values.get(path, "missing")
                    for path in selected
                }
            )

        manifest = folder / "app.json"
        if manifest in values:
            result[app] = fingerprint([manifest])
        for source in paths:
            if source.parent != folder or source.suffix != ".w4gl":
                continue
            validate_name(source.stem)
            result[f"{app}/{source.stem}"] = fingerprint(
                [
                    root / "field_defaults.json",
                    folder / "field_defaults.json",
                    *[source.with_suffix(suffix) for suffix in SUFFIXES],
                ]
            )
        report("Hashing local source", index, len(apps))
    return result


def target(connection: OpenRoadConnection) -> dict[str, str]:
    return {
        "host": connection.remote_host.ssh_target
        if connection.remote_host
        else socket.gethostname(),
        "vnode": connection.vnode,
        "database": connection.database,
    }


class Ledger:
    def __init__(self, root: Path, connection: OpenRoadConnection):
        self.path = root / ".openroad/transfers.json"
        self.target = target(connection)
        self.entries: dict[str, Any] = {}
        self.asset_dependencies: dict[str, Any] = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if data["version"] != 1 or not isinstance(data["entries"], dict):
                    raise ValueError
                if data["target"] == self.target:
                    for key, entry in data["entries"].items():
                        parts = key.split("/")
                        if len(parts) not in {1, 2} or not isinstance(entry, dict):
                            raise ValueError
                        for part in parts:
                            validate_name(part)
                        if not isinstance(entry.get("hash"), str) or not (
                            entry.get("database") is None
                            or isinstance(entry["database"], dict)
                        ):
                            raise ValueError
                    self.entries = data["entries"]
                    if isinstance(data.get("asset_dependencies"), dict):
                        self.asset_dependencies = data["asset_dependencies"]
            except (ValueError, KeyError, TypeError) as ex:
                raise ProjectError(
                    "Invalid transfer ledger; move .openroad/transfers.json aside to start a full transfer"
                ) from ex

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "version": 1,
                    "target": self.target,
                    "entries": self.entries,
                    "asset_dependencies": self.asset_dependencies,
                },
                separators=(",", ":"),
            )
            + "\n"
        )
        temporary.replace(self.path)

    def record(self, key: str, local: str, remote: dict[str, object] | None) -> None:
        self.entries[key] = {"hash": local, "database": remote}


def record_export_checkpoint(
    connection: OpenRoadConnection,
    root: Path,
    app: str,
    components: set[str],
    remote: dict[str, Any],
    output_hashes: dict[Path, str],
) -> None:
    tokens = {key.casefold(): token for key, token in remote.items()}
    exported = {app.casefold(), *(f"{app}/{name}".casefold() for name in components)}
    ledger = Ledger(root, connection)
    changed = False
    for key, fingerprint in hashes(
        root, [app], captured=output_hashes, dependency_cache=ledger.asset_dependencies
    ).items():
        slot = key.casefold()
        if slot in exported and slot in tokens:
            ledger.record(key, fingerprint, tokens[slot])
            changed = True
    if changed:
        ledger.save()


@dataclass
class Result:
    direction: str
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    deletion_backup: Path | None = None

    def summary(self) -> str:
        lines = [
            f"{self.direction.capitalize()} complete: {len(self.succeeded) + len(self.deleted)} succeeded, {len(self.failed)} failed, {len(self.skipped)} skipped"
        ]
        lines.extend(
            f"{key}: {reason}"
            for key, reason in {**self.failed, **self.skipped}.items()
        )
        lines.extend(f"Deleted {key}" for key in self.deleted)
        if self.deletion_backup is not None:
            lines.append(f"Deleted local source saved in {self.deletion_backup}")
        return "\n".join(lines)


def identity(token: dict[str, Any]) -> object:
    return token.get("base_entity_id", token.get("id"))


def app_names(root: Path, ledger: Ledger) -> set[str]:
    return {
        p.parent.name
        for p in root.glob("*/app.json")
        if not p.parent.name.startswith(".")
    } | {key.split("/")[0] for key in ledger.entries}


def prepare(
    source: Path,
    destination: Path,
    names: list[str],
    *,
    application: bool,
    result: Result,
    inputs: dict[Path, bytes] | None = None,
) -> list[str]:
    accepted: list[str] = []
    with ExitStack() as scope:
        if inputs is not None:
            scope.enter_context(captured_reads(source.parent, inputs))
        output = scope.enter_context(etree.xmlfile(str(destination), encoding="UTF-8"))
        output.write_declaration()
        with output.element("OPENROAD", nsmap=NS):
            if application:
                output.write(new_application(source))
                accepted.append(source.name)
            for index, name in enumerate(names, 1):
                report(f"Preparing {source.name}", index, len(names))
                key = f"{source.name}/{name}"
                try:
                    node = new_component(source / f"{name}.w4gl")
                    prepare_submission(node)
                    output.write(node)
                    accepted.append(key)
                except Exception as ex:
                    result.failed[key] = str(ex)
    if destination.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ProjectError("Source XML exceeds the 512 MiB document limit")
    return accepted


def submit(
    connection: OpenRoadConnection,
    app: str,
    component: str,
    xml: Path,
    log: Path,
    *,
    create: bool = False,
) -> None:
    log.unlink(missing_ok=True)
    report(
        f"Importing {app if component == '-' else app + '/' + component} with OpenROAD"
    )
    try:
        import_component_xml(connection, app, component, xml, log, create=create)
    except Exception as ex:
        diagnostic = (
            "\n".join(log.read_text(errors="replace").splitlines()[-20:])
            if log.exists()
            else ""
        )
        raise ProjectError(str(ex) + ("\n" + diagnostic if diagnostic else "")) from ex


def post_import(
    connection: OpenRoadConnection,
    root: Path,
    ledger: Ledger,
    accepted: list[str],
    local: dict[str, str],
    result: Result,
    *,
    compile: bool = False,
) -> None:
    if compile:
        from .compiler import queue_compilation

        (root / ".openroad").mkdir(exist_ok=True)
        queue_compilation(
            root,
            [(key.split("/")[0], key.split("/")[1]) for key in accepted if "/" in key],
        )
    for key in accepted:
        ledger.record(key, local[key], None)
        result.succeeded.append(key)
    ledger.save()


def refresh_tokens(
    connection: OpenRoadConnection,
    ledger: Ledger,
    result: Result,
    scope: str | None = None,
) -> None:
    pending = [
        key
        for key, entry in ledger.entries.items()
        if entry.get("database") is None and in_scope(key, scope)
    ]
    if not pending:
        return
    report("Reading database tokens for imported source")
    try:
        remote = {key.casefold(): value for key, value in inventory(connection).items()}
    except Exception as ex:
        for key in pending:
            result.failed[key] = f"Imported; database token read needs retry: {ex}"
        return
    for key in pending:
        if key.casefold() not in remote:
            result.failed[key] = (
                "Import returned success but object is absent from catalog"
            )
            ledger.entries.pop(key)
        else:
            ledger.entries[key]["database"] = remote[key.casefold()]
    ledger.save()


@validation_scope()
@resolution_scope()
def push(
    connection: OpenRoadConnection,
    root: Path,
    *,
    full: bool = False,
    dry_run: bool = False,
    compile: bool = True,
    plan: TransferPlan | None = None,
    pulled_for_compile: set[str] | None = None,
) -> Result:
    if plan is None:
        check_paths(root)
    ledger = Ledger(root, connection) if plan is None else plan.ledger
    report("Hashing local source")
    cold = full or not ledger.entries
    if plan is not None:
        local = plan.local
    elif cold:
        # Every sender object is pending; hash each application before reconstruction.
        local = local_names(
            root,
            [
                manifest.parent.name
                for manifest in root.glob("*/app.json")
                if not manifest.parent.name.startswith(".")
            ],
        )
    else:
        local = hashes(root, dependency_cache=ledger.asset_dependencies)
    changed = (
        set(plan.push)
        if plan is not None
        else {
            key
            for key, value in local.items()
            if full or ledger.entries.get(key, {}).get("hash") != value
        }
    )
    result = Result("push")
    missing_local = set(ledger.entries) - set(local)
    if plan is not None:
        missing_local = plan.missing_local & ledger.entries.keys()
    removed = missing_local if plan is None else missing_local & plan.push
    if plan is not None:
        changed -= removed
    if plan is None:
        for key in sorted(removed):
            result.failed[key] = "Use the CLI to plan a tracked source deletion"
        removed_apps = {key for key in missing_local if "/" not in key}
        for key in list(changed):
            app = key.split("/")[0]
            if key not in ledger.entries and (
                (app not in ledger.entries and removed_apps)
                or any(old.startswith(app + "/") for old in missing_local)
            ):
                result.skipped[key] = (
                    "Resolve the local deletion/rename before adding a new object in this scope"
                )
                changed.remove(key)
    if not changed:
        if not dry_run:
            refresh_tokens(connection, ledger, result, plan.scope if plan else None)
            if compile:
                retry_compilation(
                    connection,
                    root,
                    result,
                    plan.scope if plan else None,
                    additional=pulled_for_compile,
                )
        return result
    remote = inventory(connection) if plan is None else plan.remote
    pending = sorted({key.split("/")[0] for key in changed})
    planned = {app.casefold() for app in pending}
    # Create included source applications first; independent applications continue after failure.
    from .project import read_json

    dependencies: dict[str, set[str]] = {}
    for app in pending:
        try:
            metadata = read_json(root / app / "app.json")
            dependencies[app] = {
                (item if isinstance(item, str) else item["name"]).casefold()
                for item in metadata.get("included_applications", [])
                if isinstance(item, str) or not item.get("image")
            }
        except Exception as ex:
            result.failed[app] = str(ex)
    pending = [app for app in pending if app in dependencies]
    ordered: list[str] = []
    remaining = set(pending)
    while remaining:
        ready = sorted(
            app
            for app in remaining
            if not (dependencies[app] & {name.casefold() for name in remaining})
        )
        if not ready:
            for app in remaining:
                result.failed[app] = "Cyclic source application includes"
            break
        ordered.extend(ready)
        remaining.difference_update(ready)
    available = {key.casefold() for key in remote if "/" not in key}
    with tempfile.TemporaryDirectory(prefix="gorak-push-") as temporary:
        work = Path(temporary)
        for index, app in enumerate(ordered, 1):
            report("Uploading applications", index - 1, len(ordered))
            selected = sorted(
                key for key in changed if key == app or key.startswith(app + "/")
            )
            blocked = (dependencies[app] & planned) - available
            if blocked:
                for key in selected:
                    result.skipped[key] = (
                        "Required application creation failed: "
                        + ", ".join(sorted(blocked))
                    )
                continue
            try:
                create = app.casefold() not in available
                # Hash and reconstruct the same immutable bytes, one application at a time.
                inputs = {path: path.read_bytes() for path in source_files(root, app)}
                captured = hashes(
                    root,
                    [app],
                    inputs=inputs,
                    dependency_cache=ledger.asset_dependencies,
                )
                if plan is not None:
                    if (create or app in selected) and plan.scope and "/" in plan.scope:
                        raise ProjectError(
                            "Push the application before pushing an individual component"
                        )
                    keys = set(captured) if create or app in selected else set(selected)
                    if (create or app in selected) and keys != {
                        key for key in local if key == app or key.startswith(app + "/")
                    }:
                        raise ProjectError(
                            "Local application membership changed since planning; rerun the command"
                        )
                    if any(
                        local[key] and captured.get(key) != local[key] for key in keys
                    ):
                        raise ProjectError(
                            "Local source changed since planning; rerun the command"
                        )
                folder = root / app
                names = (
                    sorted(
                        p.stem
                        for p in inputs
                        if p.parent == folder and p.suffix == ".w4gl"
                    )
                    if create
                    else [key.split("/")[1] for key in selected if "/" in key]
                )
                if create or app in selected:
                    names = sorted(
                        p.stem
                        for p in inputs
                        if p.parent == folder and p.suffix == ".w4gl"
                    )
                    submitted = work / "application.xml"
                    accepted = prepare(
                        folder,
                        submitted,
                        names,
                        application=True,
                        result=result,
                        inputs=inputs,
                    )
                    if dry_run:
                        result.succeeded.extend(accepted)
                        available.add(app.casefold())
                        continue
                    if not create and any(
                        key.startswith(app + "/") for key in result.failed
                    ):
                        result.failed[app] = (
                            "Application metadata not replaced because a component could not be converted"
                        )
                        completed: list[str] = []
                        for node in application_children(submitted):
                            if node.tag != "COMPONENT":
                                continue
                            name = str(node.get("name"))
                            key = f"{app}/{name}"
                            try:
                                component_xml = work / "partial.xml"
                                component_xml.write_bytes(document([node]))
                                (work / "import.log").unlink(missing_ok=True)
                                submit(
                                    connection,
                                    app,
                                    name,
                                    component_xml,
                                    work / "import.log",
                                )
                                completed.append(key)
                            except Exception as ex:
                                result.failed[key] = str(ex)
                        if completed:
                            post_import(
                                connection,
                                root,
                                ledger,
                                completed,
                                captured,
                                result,
                                compile=compile,
                            )
                        continue
                    (work / "import.log").unlink(missing_ok=True)
                    submit(
                        connection,
                        app,
                        "-",
                        submitted,
                        work / "import.log",
                        create=create,
                    )
                    available.add(app.casefold())
                    post_import(
                        connection,
                        root,
                        ledger,
                        accepted,
                        captured,
                        result,
                        compile=compile,
                    )
                else:
                    jobs = ([app] if app in selected else []) + [
                        f"{app}/{name}" for name in names
                    ]
                    for key in jobs:
                        try:
                            submitted = work / "component.xml"
                            accepted = prepare(
                                folder,
                                submitted,
                                [] if key == app else [key.split("/")[1]],
                                application=key == app,
                                result=result,
                                inputs=inputs,
                            )
                            if not accepted:
                                continue
                            if dry_run:
                                result.succeeded.extend(accepted)
                                continue
                            (work / "import.log").unlink(missing_ok=True)
                            submit(
                                connection,
                                app,
                                "-" if key == app else key.split("/")[1],
                                submitted,
                                work / "import.log",
                            )
                            post_import(
                                connection,
                                root,
                                ledger,
                                accepted,
                                captured,
                                result,
                                compile=compile,
                            )
                        except Exception as ex:
                            result.failed[key] = str(ex)
            except Exception as ex:
                result.failed[app] = str(ex)
                for key in selected:
                    if key != app and key not in result.failed:
                        result.skipped[key] = "Application import failed"
            report("Uploading applications", index, len(ordered))
        if compile and not dry_run:
            retry_compilation(
                connection,
                root,
                result,
                plan.scope if plan else None,
                additional=pulled_for_compile,
            )
    if not dry_run:
        refresh_tokens(connection, ledger, result, plan.scope if plan else None)
    return result


def retry_compilation(
    connection: OpenRoadConnection,
    root: Path,
    result: Result,
    scope: str | None = None,
    *,
    additional: set[str] | None = None,
) -> None:
    from .atomic_json import write_record
    from .compiler import compile_source, read_compile_queue

    path = root / ".openroad/compile-pending.json"
    if not path.exists():
        return
    try:
        targets = read_compile_queue(path)
        failed = []
        for app, name in targets:
            key = f"{app}/{name}"
            if not in_scope(key, scope) and (
                additional is None or key not in additional
            ):
                failed.append((app, name))
                continue
            log = root / ".openroad/compiles" / app / (name + ".log")
            try:
                log.parent.mkdir(parents=True, exist_ok=True)
                log.unlink(missing_ok=True)
                outcome = compile_source(connection, app, name, log)
                if not outcome.success:
                    raise ProjectError(outcome.diagnostics())
            except Exception as ex:
                failed.append((app, name))
                result.failed[f"{app}/{name}"] = f"Database compilation failed: {ex}"
        if failed:
            write_record(path, [list(item) for item in failed])
        else:
            path.unlink()
    except (ValueError, OSError) as ex:
        result.failed["compilation"] = f"Cannot read pending compilation: {ex}"


def pull_scope(root: Path, ledger: Ledger, remote: dict[str, Any]) -> set[str]:
    apps = app_names(root, ledger)
    if not apps:
        apps = {key for key in remote if "/" not in key}
    # Application renames remain discoverable through stable catalog identity.
    app_ids = {
        identity(value["database"])
        for key, value in ledger.entries.items()
        if "/" not in key and isinstance(value.get("database"), dict)
    }
    apps.update(
        key
        for key, token in remote.items()
        if "/" not in key and identity(token) in app_ids
    )
    return apps


@validation_scope()
@resolution_scope()
def pull(
    connection: OpenRoadConnection,
    root: Path,
    *,
    full: bool = False,
    dry_run: bool = False,
    plan: TransferPlan | None = None,
) -> Result:
    if plan is None:
        check_paths(root)
    ledger = Ledger(root, connection) if plan is None else plan.ledger
    report("Reading database change tokens")
    remote = inventory(connection) if plan is None else plan.remote
    apps = pull_scope(root, ledger, remote)
    prior = {key.casefold(): value for key, value in ledger.entries.items()}
    scoped_apps = {app.casefold() for app in apps}
    changed = (
        plan.pull
        if plan is not None
        else {
            key
            for key, token in remote.items()
            if key.split("/")[0].casefold() in scoped_apps
            and (full or prior.get(key.casefold(), {}).get("database") != token)
        }
    )
    catalog_keys = {key.casefold(): key for key in remote}
    identities = {
        ("/" in key, identity(entry["database"])): key
        for key, entry in ledger.entries.items()
        if isinstance(entry.get("database"), dict)
    }
    result = Result("pull")
    if dry_run:
        result.succeeded.extend(sorted(changed))
        return result
    names = sorted({key.split("/")[0] for key in changed})
    # Export exceptions are collected by the worker so one failed app doesn't close the stream.
    export_errors: dict[str, str] = {}

    def backup(app: str, path: Path) -> None:
        try:
            backup_application_xml(connection, app, path)
        except Exception as ex:
            export_errors[app] = str(ex)

    from .export_pipeline import prefetched_exports

    with (
        ExitStack() as stages,
        prefetched_exports(names, connection.export_workers, backup) as exports,
    ):
        for index, (app, xml) in enumerate(exports, 1):
            if app in export_errors:
                result.failed[app] = export_errors[app]
                continue
            try:
                folder = root / app
                folder.mkdir(parents=True, exist_ok=True)
                writer = AssetWriter(folder)
                output_hashes: dict[Path, str] = {}
                staging = Path(
                    stages.enter_context(
                        tempfile.TemporaryDirectory(prefix=".gorak-stage-", dir=folder)
                    )
                )
                case_index: dict[str, list[Path]] = {}
                for path in folder.iterdir():
                    case_index.setdefault(path.name.lower(), []).append(path)
                accepted: list[str] = []
                styles = parent_styles(folder)
                count = sum(key == app or key.startswith(app + "/") for key in changed)
                converted = 0
                report(f"Converting {app}", 0, count)
                for native in application_children(xml):
                    name = native.get("name", "")
                    key = app if native.tag == "APPLICATION" else f"{app}/{name}"
                    catalog_key = catalog_keys.get(key.casefold())
                    if catalog_key not in changed:
                        continue
                    try:
                        validate_name(name)
                        if native.tag == "APPLICATION":
                            tree = etree.Element("OPENROAD")
                            tree.append(externalize(native, folder, app, writer=writer))
                            parsed = parse_application_xml(tree)
                            payload = (
                                json.dumps(
                                    application_metadata(
                                        parsed.application,
                                        included_applications=parsed.included_applications,
                                    ),
                                    indent=4,
                                )
                                + "\n"
                            )
                            staged = folder / ".app.json.tmp"
                            write_text(staged, payload, digests=output_hashes)
                            staged.replace(folder / "app.json")
                            output_hashes[folder / "app.json"] = output_hashes.pop(
                                staged
                            )
                        else:
                            project_component_files(
                                native,
                                folder,
                                writer,
                                None,
                                parent_styles=styles,
                                case_index=case_index,
                                staging=staging,
                                digests=output_hashes,
                            )
                        accepted.append(key)
                    except Exception as ex:
                        result.failed[key] = str(ex)
                    converted += 1
                    report(f"Converting {app}", converted, count)
                local = hashes(
                    root,
                    [app],
                    captured=output_hashes,
                    dependency_cache=ledger.asset_dependencies,
                )
                replacements = []
                for key in accepted:
                    token = remote[catalog_keys[key.casefold()]]
                    old = identities.get(("/" in key, identity(token)))
                    if old and old != key:
                        replacements.append((old, key))
                # Protect every current catalog destination, including swaps, chains,
                # and destinations belonging to another application in this batch.
                protected = {key.casefold() for key in remote}
                for old, key in replacements:
                    if (
                        old.casefold() not in protected
                        or old.casefold() == key.casefold()
                    ):
                        paths = (
                            [root / (old + suffix) for suffix in SUFFIXES]
                            if "/" in old
                            else [root / old / "app.json"]
                        )
                        for previous in paths:
                            current = (
                                root / (key + previous.name[len(Path(old).name) :])
                                if "/" in old
                                else root / key / "app.json"
                            )
                            if not (
                                previous.exists()
                                and current.exists()
                                and previous.samefile(current)
                            ):
                                previous.unlink(missing_ok=True)
                    # Do not discard a replacement checkpoint written by an earlier app.
                    entry = ledger.entries.get(old)
                    if entry and identity(entry.get("database") or {}) == identity(
                        remote[catalog_keys[key.casefold()]]
                    ):
                        ledger.entries.pop(old)
                for key in accepted:
                    token = remote[catalog_keys[key.casefold()]]
                    ledger.record(key, local[key], token)
                    result.succeeded.append(key)
                accepted_names = {item.casefold() for item in accepted}
                for key in changed:
                    if (
                        (key == app or key.startswith(app + "/"))
                        and key.casefold() not in accepted_names
                        and key not in result.failed
                    ):
                        result.failed[key] = (
                            "Catalog object is missing from the native XML export"
                        )
                ledger.save()
            except Exception as ex:
                result.failed[app] = str(ex)
            report("Downloading applications", index, len(names))
    return result


def in_scope(key: str, scope: str | None) -> bool:
    if scope is None:
        return True
    key, scope = key.casefold(), scope.casefold()
    return key == scope or key.startswith(scope + "/")


def transfer_scope(root: Path, cwd: Path, target: str | None) -> str | None:
    relative = cwd.resolve().relative_to(root.resolve())
    app = relative.parts[0] if relative.parts else None
    if app is not None and not (root / app / "app.json").is_file():
        app = None
    if target is None:
        return app
    parts = target.replace("!", "/").split("/")
    if len(parts) > 2:
        raise ProjectError("Use APP, APP/COMPONENT, or APP!COMPONENT")
    for part in parts:
        validate_name(part)
    if len(parts) == 1 and app is not None:
        parts.insert(0, app)
    return "/".join(parts)


@dataclass(frozen=True)
class Conflict:
    local: str
    database: str
    reason: str


@dataclass
class TransferPlan:
    ledger: Ledger
    local: dict[str, str]
    remote: dict[str, Any]
    scope: str | None
    push: set[str]
    pull: set[str]
    conflicts: list[Conflict]
    renamed: dict[str, str]
    missing_local: set[str]
    database_deletions: set[str]
    acknowledged_deletions: set[str]

    def preview(self) -> dict[str, object]:
        result: dict[str, object] = {
            "push": sorted(self.push),
            "pull": sorted(self.pull),
            "conflicts": [
                {"local": item.local, "database": item.database, "reason": item.reason}
                for item in self.conflicts
            ],
        }
        if self.database_deletions:
            result["database_deletions"] = sorted(self.database_deletions)
        if removed := self.push & self.missing_local:
            result["local_deletions"] = sorted(removed)
        if moves := {new: old for old, new in self.renamed.items() if new in self.pull}:
            result["renames"] = moves
        return result


def local_names(root: Path, apps: list[str]) -> dict[str, str]:
    return {
        key: ""
        for app in apps
        for key in [
            app,
            *(f"{app}/{path.stem}" for path in (root / app).glob("*.w4gl")),
        ]
    }


def local_source_absent(root: Path, key: str) -> bool:
    path = root / key
    if "/" not in key:
        return not path.exists()
    return not any(path.with_suffix(suffix).exists() for suffix in SUFFIXES)


def plan_transfer(
    connection: OpenRoadConnection,
    root: Path,
    *,
    scope: str | None = None,
    direction: str = "sync",
    full: bool = False,
    prefer: str | None = None,
) -> TransferPlan:
    check_paths(root)
    ledger = Ledger(root, connection)
    report("Reading database change tokens")
    remote = inventory(connection)
    remote_keys = {key.casefold(): key for key in remote}
    previous = {key.casefold(): entry for key, entry in ledger.entries.items()}
    previous_ids = {
        ("/" in key, identity(token)): key
        for key, entry in ledger.entries.items()
        if isinstance(token := entry.get("database"), dict)
        and identity(token) is not None
    }
    renamed = {
        old: key
        for key, token in remote.items()
        if (old := previous_ids.get(("/" in key, identity(token)))) is not None
        and old.casefold() != key.casefold()
    }
    old_names = {key: old for old, key in renamed.items()}
    app_scope = scope.split("/", 1)[0] if scope else None
    scoped_apps = {app_scope.casefold()} if app_scope else set()
    for old, new in renamed.items():
        if "/" not in old and (
            old.casefold() in scoped_apps or new.casefold() in scoped_apps
        ):
            scoped_apps.update((old.casefold(), new.casefold()))
    apps = sorted(
        p.parent.name
        for p in root.glob("*/app.json")
        if not p.parent.name.startswith(".")
        and (not scoped_apps or p.parent.name.casefold() in scoped_apps)
    )
    report("Hashing local source")
    # Presence is enough for cold planning. Push captures and hashes the bytes
    # once per application when preparing the actual import.
    local = (
        hashes(root, apps, dependency_cache=ledger.asset_dependencies)
        if ledger.entries
        else local_names(root, apps)
    )
    local_keys = {key.casefold(): key for key in local}

    def selected(key: str, aliases: dict[str, str], names: dict[str, str]) -> bool:
        if in_scope(key, scope):
            return True
        if scope and "/" in scope and scope.casefold() in names:
            return False
        alias = aliases.get(key)
        return alias is not None and in_scope(alias, scope)

    if scope and not any(
        in_scope(key, scope) for key in {*local, *remote, *ledger.entries}
    ):
        raise ProjectError(f"Unknown transfer target: {scope}")
    pull_apps = {app.casefold() for app in apps}
    pull_apps.update(
        new.casefold()
        for old, new in renamed.items()
        if "/" not in old and old.casefold() in pull_apps
    )
    database_changes = {
        key
        for key, token in remote.items()
        if previous.get(key.casefold(), {}).get("database") != token
    }
    restore_apps: set[str] = set()
    if prefer == "pull" and direction != "push" and (scope is None or "/" not in scope):
        for key, entry in ledger.entries.items():
            if "/" in key or not isinstance(entry.get("database"), dict):
                continue
            current = renamed.get(key, key).casefold()
            if current in pull_apps or current not in remote_keys:
                continue
            if not (in_scope(key, scope) or in_scope(current, scope)):
                continue
            if full or any(in_scope(name, current) for name in database_changes):
                restore_apps.add(current)
        pull_apps.update(restore_apps)
    if (
        app_scope
        and app_scope.casefold() not in pull_apps
        and (
            direction == "pull"
            or (direction == "sync" and app_scope.casefold() in remote_keys)
        )
    ):
        raise ProjectError(
            f"{app_scope} is not in this project. Use gorak app export {app_scope} to add it."
        )
    missing_local = {
        key
        for key in ledger.entries
        if (not scoped_apps or key.split("/", 1)[0].casefold() in scoped_apps)
        and key.casefold() not in local_keys
    }
    deleted = {
        key
        for key, entry in ledger.entries.items()
        if isinstance(token := entry.get("database"), dict)
        and identity(token) is not None
        and key.casefold() not in remote_keys
        and key not in renamed
    }
    acknowledged = {
        key
        for key in deleted & missing_local
        if in_scope(key, scope) and local_source_absent(root, key)
    }
    # Both primary source objects are gone. Any local companion files still
    # need to be moved aside on pull.
    missing_local -= deleted
    deleted -= acknowledged
    pending_deletions = {
        key for key in deleted if direction != "push" and in_scope(key, scope)
    }
    # A removed application represents the whole namespace in the report.
    database_deletions = {
        key
        for key in pending_deletions
        if "/" not in key or key.split("/", 1)[0] not in pending_deletions
    }
    local_changes = missing_local | {
        key
        for key, value in local.items()
        if previous.get(key.casefold(), {}).get("hash") != value
    }
    push = {
        key
        for key in (set(local) | local_changes if full else local_changes)
        if selected(key, renamed, local_keys) and direction != "pull"
    }
    pull = {
        key
        for key in remote
        if (
            full
            or key in database_changes
            or key.split("/", 1)[0].casefold() in restore_apps
        )
        and selected(key, old_names, remote_keys)
        and direction != "push"
        and key.split("/", 1)[0].casefold() in pull_apps
    }

    # Workbench renames occupy both the previous and the current local slots.
    # An application import also writes its component namespace.
    push_by_slot = {key.casefold(): key for key in push}
    whole_apps = {key.casefold(): key for key in push if "/" not in key}
    if not (scope and "/" in scope):
        for key in sorted(push):
            app = key.split("/", 1)[0]
            if app.casefold() not in remote_keys and app in local:
                whole_apps.setdefault(app.casefold(), app)
    changed_local_by_slot = {key.casefold(): key for key in local_changes}
    conflicts: dict[tuple[str, str], Conflict] = {}
    moved_or_deleted = set(old_names) | deleted
    for key in sorted(database_changes | pull | deleted):
        slots = {key.casefold(), old_names.get(key, key).casefold()}
        senders = {
            sender
            for slot in slots
            for sender in (
                push_by_slot.get(slot),
                whole_apps.get(slot.split("/", 1)[0]),
                changed_local_by_slot.get(slot)
                if key in pull or key in pending_deletions
                else None,
            )
            if sender is not None
        }
        # A component push cannot safely recreate an application renamed or
        # removed in Workbench.
        if "/" not in key and key in moved_or_deleted:
            senders.update(
                sender
                for slot, sender in push_by_slot.items()
                if slot.split("/", 1)[0] in slots
            )
            if key in pending_deletions:
                senders.update(
                    sender
                    for slot, sender in changed_local_by_slot.items()
                    if slot.split("/", 1)[0] in slots
                )
        for sender in sorted(senders):
            if sender not in push and key not in pull and key not in pending_deletions:
                continue
            prior = previous.get(sender.casefold())
            if key in deleted:
                reason = "Database object was deleted"
            elif key in old_names:
                reason = "Database object was renamed"
            elif prior is None or prior.get("database") is None:
                reason = "No shared transfer checkpoint"
            elif sender.casefold() not in slots:
                reason = "Application push would overwrite a database change"
            else:
                reason = "Local and database changes overlap"
            conflicts[sender, key] = Conflict(sender, key, reason)
    return TransferPlan(
        ledger,
        local,
        remote,
        scope,
        push,
        pull,
        list(conflicts.values()),
        renamed,
        missing_local,
        database_deletions,
        acknowledged,
    )


def forget_deleted(root: Path, ledger: Ledger, key: str) -> None:
    from .compiler import clear_compiled_targets

    for recorded in list(ledger.entries):
        if in_scope(recorded, key):
            ledger.entries.pop(recorded)
    ledger.save()
    app, _, component = key.partition("/")
    clear_compiled_targets(root, app, component or None)


def apply_local_deletions(root: Path, plan: TransferPlan, result: Result) -> None:
    backup = root / ".openroad/deletions" / uuid4().hex
    by_app: dict[str, dict[str, str]] = {}
    for key in sorted(plan.database_deletions):
        app, _, component = key.partition("/")
        moved: list[tuple[Path, Path]] = []
        try:
            if app not in by_app:
                by_app[app] = hashes(root, [app])
            current = by_app[app]
            expected = {
                name: value for name, value in plan.local.items() if in_scope(name, key)
            }
            actual = {
                name: value for name, value in current.items() if in_scope(name, key)
            }
            if actual != expected:
                raise ProjectError(
                    "Local source changed since planning; rerun the command"
                )
            folder = root / app
            paths = (
                [folder / f"{component}{suffix}" for suffix in SUFFIXES]
                if component
                else [folder]
            )
            for path in paths:
                if not path.exists():
                    continue
                destination = backup / path.relative_to(root)
                destination.parent.mkdir(parents=True, exist_ok=True)
                path.rename(destination)
                moved.append((path, destination))
        except (OSError, ProjectError) as ex:
            for path, destination in reversed(moved):
                if not path.exists():
                    destination.rename(path)
                else:
                    result.deletion_backup = backup.relative_to(root)
            result.failed[key] = str(ex)
            continue
        result.deleted.append(key)
        if moved:
            result.deletion_backup = backup.relative_to(root)
        try:
            forget_deleted(root, plan.ledger, key)
        except (OSError, ValueError, ProjectError) as ex:
            result.failed[key] = (
                f"Local source removed; could not record deletion: {ex}"
            )


def apply_database_deletions(
    connection: OpenRoadConnection,
    root: Path,
    plan: TransferPlan,
    result: Result,
    replacements: set[str],
) -> None:
    requested = (plan.push & plan.missing_local) | replacements
    targets = sorted(
        key
        for key in requested
        if "/" not in key or key.split("/", 1)[0] not in requested
    )
    if not targets:
        return
    planned = {key.casefold(): value for key, value in plan.remote.items()}
    try:
        current = {
            key.casefold(): value for key, value in inventory(connection).items()
        }
    except Exception as ex:
        for key in targets:
            result.failed[key] = f"Could not verify source before deletion: {ex}"
        return
    actual_names = {key.casefold(): key for key in plan.remote}
    submitted: dict[str, str] = {}
    log_dir = root / ".openroad/deletions" / uuid4().hex
    failed_imports = set(result.failed) | set(result.skipped)
    additions = {
        key for key in plan.push if key in plan.local and key.casefold() not in planned
    }
    for key in targets:
        app, _, component = key.partition("/")
        if any(
            (in_scope(added, app) if component else "/" not in added)
            and any(
                in_scope(added, failed) or in_scope(failed, added)
                for failed in failed_imports
            )
            for added in additions
        ):
            result.skipped[key] = "A related import failed; the original was kept"
            continue
        replacement = key in replacements
        if replacement and key not in result.succeeded:
            result.skipped[key] = (
                "The local version was not imported; the renamed source was kept"
            )
            continue
        old = plan.ledger.entries[key].get("database")
        slot = plan.renamed.get(key, key).casefold()
        token = planned.get(slot)
        if not replacement and (
            not isinstance(old, dict)
            or not token
            or identity(old) is None
            or identity(old) != identity(token)
        ):
            result.failed[key] = (
                "Cannot verify the database identity of the deleted source"
            )
            continue
        if (
            not replacement
            and (root / (key + ".w4gl") if component else root / app).exists()
        ):
            result.failed[key] = (
                "Local source still exists; remove it before deleting in Workbench"
            )
            continue
        if {name: value for name, value in planned.items() if in_scope(name, slot)} != {
            name: value for name, value in current.items() if in_scope(name, slot)
        }:
            result.failed[key] = (
                "Database source changed since planning; rerun the command"
            )
            continue
        actual_app, _, actual_component = actual_names[slot].partition("/")
        try:
            if replacement:
                # The old-name import has succeeded. Keep the renamed object
                # pending for deletion if native cleanup cannot finish now.
                plan.ledger.record(actual_names[slot], "", planned[slot])
                plan.ledger.save()
            delete_database_source(
                connection,
                actual_app,
                actual_component or None,
                log_dir / f"{actual_app}-{actual_component or 'application'}.log",
            )
        except Exception as ex:
            result.failed[key] = str(ex)
        else:
            submitted[key] = slot
    if submitted:
        try:
            remaining = {
                key.casefold(): token for key, token in inventory(connection).items()
            }
        except Exception as ex:
            for key in submitted:
                result.failed[key] = (
                    f"Deletion submitted; could not confirm catalog result: {ex}"
                )
            return
        for key, slot in submitted.items():
            if any(
                in_scope(name, slot)
                or (
                    ("/" in name) == ("/" in slot)
                    and identity(token) == identity(planned[slot])
                )
                for name, token in remaining.items()
            ):
                result.failed[key] = (
                    "OpenROAD did not remove the source from the catalog"
                )
            else:
                try:
                    forget_deleted(
                        root,
                        plan.ledger,
                        actual_names[slot] if key in replacements else key,
                    )
                except (OSError, ValueError, ProjectError) as ex:
                    result.failed[key] = (
                        f"Database source removed; could not record deletion: {ex}"
                    )
                result.deleted.append(actual_names[slot])


def replacements_for_renames(plan: TransferPlan, prefer: str | None) -> set[str]:
    moved = {old.casefold(): (old, new) for old, new in plan.renamed.items()}
    remote = {key.casefold() for key in plan.remote}
    replacements: set[str] = set()
    for key in sorted(plan.push - plan.missing_local):
        app = key.split("/", 1)[0]
        move = moved.get(app.casefold()) or moved.get(key.casefold())
        if move is None:
            continue
        old, new = move
        if (
            prefer != "push"
            or old.casefold() in remote
            or old not in plan.push
            or any(in_scope(local, new) for local in plan.local)
        ):
            raise ProjectError(
                f"{key} was renamed in Workbench to {new}. "
                "Pull the rename or force-push the original application or component if its old name is free."
            )
        replacements.add(old)
    for old in replacements:
        new = plan.renamed[old]
        plan.pull = {key for key in plan.pull if not in_scope(key, new)}
    return replacements


def execute_transfer(
    connection: OpenRoadConnection,
    root: Path,
    *,
    direction: str,
    scope: str | None = None,
    full: bool = False,
    dry_run: bool = False,
    compile: bool = False,
    prefer: str | None = None,
) -> str:
    if full and direction == "sync":
        raise ProjectError(
            "Use push --full or pull --full to select the source of a full transfer"
        )
    plan = plan_transfer(
        connection, root, scope=scope, direction=direction, full=full, prefer=prefer
    )
    deferred_apps: set[str] = set()
    if prefer == "push":
        plan.pull.difference_update(
            item.database for item in plan.conflicts if item.local in plan.push
        )
        plan.database_deletions.difference_update(
            item.database for item in plan.conflicts if item.local in plan.push
        )
    elif prefer == "pull":
        pulled_slots = {key.casefold() for key in plan.pull}

        def database_wins(key: str) -> bool:
            return key.casefold() in pulled_slots or any(
                in_scope(key, deleted) for deleted in plan.database_deletions
            )

        unresolved = [
            item
            for item in plan.conflicts
            if item.local in plan.push
            and not database_wins(item.database)
            and direction == "sync"
        ]
        if unresolved and not dry_run:
            raise ProjectError(
                "Workbench has no transferable source for: "
                + ", ".join(sorted({item.database for item in unresolved}))
                + ". Resolve the deletion or rename before syncing."
            )
        overridden = {
            item.local for item in plan.conflicts if database_wins(item.database)
        }
        deferred_apps = {
            key
            for key in overridden & plan.push
            if "/" not in key and not database_wins(key)
        }
        plan.push.difference_update(overridden)
    replacements = replacements_for_renames(plan, prefer) if prefer == "push" else set()
    if dry_run:
        preview = plan.preview()
        if replacements:
            preview["replace_database_renames"] = sorted(
                plan.renamed[key] for key in replacements
            )
        if deferred_apps:
            preview["deferred_application_pushes"] = sorted(deferred_apps)
        return json.dumps(preview, indent=2)
    if plan.conflicts and prefer is None:
        details = "\n".join(
            f"{item.local} / {item.database}: {item.reason}" for item in plan.conflicts
        )
        hint = (
            "Resolve components individually or use --force-push or --force-pull."
            if direction == "sync"
            else f"Rerun with --force to keep the {'local' if direction == 'push' else 'Workbench'} version in this scope."
        )
        raise ProjectError(f"Transfer conflicts:\n{details}\n{hint}")

    if prefer != "push":
        replacements_for_renames(plan, prefer)
    if scope and "/" in scope:
        local_apps = {key.casefold() for key in plan.local if "/" not in key}
        remote_apps = {key.casefold() for key in plan.remote if "/" not in key}
        if any(key.split("/", 1)[0].casefold() not in local_apps for key in plan.pull):
            raise ProjectError(
                "Export the application before pulling an individual component"
            )
        if any(
            key.split("/", 1)[0].casefold() not in remote_apps
            for key in plan.push - plan.missing_local
        ):
            raise ProjectError(
                "Push the application before pushing an individual component"
            )
    results = []
    pulled_for_compile: set[str] = set()
    if plan.acknowledged_deletions:
        for key in plan.acknowledged_deletions:
            plan.ledger.entries.pop(key)
        plan.ledger.save()
    if direction != "push":
        pulled = pull(connection, root, plan=plan)
        results.append(pulled)
        apply_local_deletions(root, plan, pulled)
        if compile:
            from .compiler import queue_compilation

            targets = [
                (app, component)
                for app, _, component in (
                    key.partition("/") for key in pulled.succeeded
                )
                if component
            ]
            if targets:
                queue_compilation(root, targets)
                pulled_for_compile = {
                    f"{app}/{component}" for app, component in targets
                }
            if direction == "pull":
                retry_compilation(
                    connection, root, pulled, scope, additional=pulled_for_compile
                )
    if direction != "pull":
        pushed = push(
            connection,
            root,
            compile=compile,
            plan=plan,
            pulled_for_compile=pulled_for_compile,
        )
        apply_database_deletions(connection, root, plan, pushed, replacements)
        results.append(pushed)
    summary = "\n".join(result.summary() for result in results)
    if deferred_apps:
        summary += (
            "\nApplication pushes still pending after conflict resolution: "
            + ", ".join(sorted(deferred_apps))
        )
    if any(result.failed or result.skipped for result in results):
        raise ProjectError(summary)
    return summary


def status(connection: OpenRoadConnection, root: Path) -> dict[str, object]:
    result = plan_transfer(connection, root).preview()
    queue = root / ".openroad/compile-pending.json"
    if queue.exists():
        from .compiler import read_compile_queue

        result["compile"] = [f"{app}/{name}" for app, name in read_compile_queue(queue)]
    return result


def format_status(state: dict[str, object]) -> str:
    sections = []
    removed = set(cast(list[str], state.get("local_deletions", [])))
    renamed = cast(dict[str, str], state.get("renames", {}))
    for key, marker, label in (
        ("push", "->", "Pending push"),
        ("pull", "<-", "Pending pull"),
        ("database_deletions", "--", "Deleted in Workbench"),
        ("compile", "**", "Pending compilation"),
    ):
        items = cast(list[str], state.get(key, []))
        if items:
            sections.append(
                "\n".join(
                    [
                        f"{label} ({len(items)}):",
                        *(
                            f"{marker} {item} (delete)"
                            if key == "push" and item in removed
                            else f"{marker} {item} (renamed from {renamed[item]})"
                            if key == "pull" and item in renamed
                            else f"{marker} {item}"
                            for item in items
                        ),
                    ]
                )
            )
    conflicts = cast(list[dict[str, str]], state["conflicts"])
    if conflicts:
        lines = [f"Conflicts ({len(conflicts)}):"]
        for conflict in conflicts:
            local, database = conflict["local"], conflict["database"]
            target = local if local == database else f"{local} <> {database}"
            lines.append(f"!! {target} ({conflict['reason']})")
        sections.append("\n".join(lines))
    return "\n\n".join(sections) or "No pending transfers."

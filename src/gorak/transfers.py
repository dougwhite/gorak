"""Sender-authoritative incremental transfers with a small successful-transfer ledger."""

import hashlib
import json
import os
import socket
import tempfile
import tomllib
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

from .connection import OpenRoadConnection
from .export import (
    application_metadata,
    backup_application_xml,
    project_component_files,
)
from .image_assets import AssetWriter, externalize
from .import_backend import import_component_xml
from .importer import validate_name
from .native_styles import parent_styles, resolution_scope, validation_scope
from .operation_progress import report
from .parser import NS, parse_application_xml
from .project import ProjectError
from .source_output import write_text
from .source_reads import captured as captured_reads
from .source_xml import MAX_DOCUMENT_BYTES, application_children
from .transfer_catalog import inventory
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

    def visit(value: Any) -> None:
        if isinstance(value, str) and value.startswith("images/"):
            from .image_assets import asset_path

            found.add(asset_path(path.parent, value))
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    try:
        if path.suffix == ".wml":
            from .source_xml import from_bytes

            for node in from_bytes(data).iter():
                visit(dict(node.attrib))
        elif path.suffix == ".w4gl":
            visit(tomllib.loads(data.decode("utf-8").split("===", 1)[0]))
        else:
            value = json.loads(data)
            visit(
                value.get("window_icon")
                if path.name == "app.json" and isinstance(value, dict)
                else value
            )
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


@dataclass
class Result:
    direction: str
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"{self.direction.capitalize()} complete: {len(self.succeeded)} succeeded, {len(self.failed)} failed, {len(self.skipped)} skipped"
        ]
        lines.extend(
            f"{key}: {reason}"
            for key, reason in {**self.failed, **self.skipped}.items()
        )
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
    connection: OpenRoadConnection, ledger: Ledger, result: Result
) -> None:
    pending = [
        key for key, entry in ledger.entries.items() if entry.get("database") is None
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
) -> Result:
    check_paths(root)
    ledger = Ledger(root, connection)
    report("Hashing local source")
    cold = full or not ledger.entries
    if cold:
        # Every sender object is pending; hash each application before reconstruction.
        local = {
            key: ""
            for manifest in root.glob("*/app.json")
            if not manifest.parent.name.startswith(".")
            for key in [
                manifest.parent.name,
                *[
                    f"{manifest.parent.name}/{path.stem}"
                    for path in manifest.parent.glob("*.w4gl")
                ],
            ]
        }
    else:
        local = hashes(root, dependency_cache=ledger.asset_dependencies)
    changed = {
        key
        for key, value in local.items()
        if full or ledger.entries.get(key, {}).get("hash") != value
    }
    result = Result("push")
    removed = set(ledger.entries) - set(local)
    for key in sorted(removed):
        result.failed[key] = (
            "Local deletion or rename requires a native database operation; it is not imported as a duplicate"
        )
    removed_apps = {key for key in removed if "/" not in key}
    for key in list(changed):
        app = key.split("/")[0]
        new = key not in ledger.entries
        ambiguous = (app not in ledger.entries and removed_apps) or any(
            old.startswith(app + "/") for old in removed
        )
        if new and ambiguous:
            result.skipped[key] = (
                "Resolve the local deletion/rename before adding a new object in this scope"
            )
            changed.remove(key)
    if not changed:
        if not dry_run:
            refresh_tokens(connection, ledger, result)
            if compile:
                retry_compilation(connection, root, result)
        return result
    remote = inventory(connection)
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
            retry_compilation(connection, root, result)
    if not dry_run:
        refresh_tokens(connection, ledger, result)
    return result


def retry_compilation(
    connection: OpenRoadConnection, root: Path, result: Result
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
            log = root / ".openroad/compiles" / app / (name + ".log")
            try:
                log.parent.mkdir(parents=True, exist_ok=True)
                log.unlink(missing_ok=True)
                outcome = compile_source(connection, app, name, log)
                if not outcome.success:
                    raise ProjectError(outcome.diagnostics())
            except Exception as ex:
                failed.append((app, name))
                result.failed[f"{app}/{name}"] = (
                    f"Source imported; compilation failed: {ex}"
                )
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
) -> Result:
    check_paths(root)
    ledger = Ledger(root, connection)
    report("Reading database change tokens")
    remote = inventory(connection)
    apps = pull_scope(root, ledger, remote)
    prior = {key.casefold(): value for key, value in ledger.entries.items()}
    scoped_apps = {app.casefold() for app in apps}
    changed = {
        key
        for key, token in remote.items()
        if key.split("/")[0].casefold() in scoped_apps
        and (full or prior.get(key.casefold(), {}).get("database") != token)
    }
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
                protected = set(remote)
                for old, key in replacements:
                    if old not in protected:
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


def status(connection: OpenRoadConnection, root: Path) -> dict[str, object]:
    check_paths(root)
    ledger = Ledger(root, connection)
    report("Hashing local source")
    local = hashes(root, dependency_cache=ledger.asset_dependencies)
    report("Reading database change tokens")
    remote = inventory(connection)
    apps = {app.casefold() for app in pull_scope(root, ledger, remote)}
    prior = {key.casefold(): value for key, value in ledger.entries.items()}
    result: dict[str, object] = {
        "push": sorted(
            {
                key
                for key, value in local.items()
                if ledger.entries.get(key, {}).get("hash") != value
            }
            | (set(ledger.entries) - set(local))
        ),
        "pull": sorted(
            key
            for key, value in remote.items()
            if (not apps or key.split("/")[0].casefold() in apps)
            and prior.get(key.casefold(), {}).get("database") != value
        ),
    }
    queue = root / ".openroad/compile-pending.json"
    if queue.exists():
        from .compiler import read_compile_queue

        result["compile"] = [f"{app}/{name}" for app, name in read_compile_queue(queue)]
    return result

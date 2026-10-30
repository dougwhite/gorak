"""Sender-authoritative incremental transfers with a small successful-transfer ledger."""

import hashlib
import json
import shutil
import socket
import tempfile
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


def hashes(root: Path, apps: list[str] | None = None) -> dict[str, str]:
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
    read: dict[Path, str] = {}
    for index, app in enumerate(apps, 1):
        validate_name(app)
        folder = root / app
        values: dict[str, str] = {}
        for path in source_files(root, app):
            if path not in read:
                read[path] = digest(path.read_bytes())
            values[path.relative_to(root).as_posix()] = read[path]
        shared = {
            name: value
            for name, value in values.items()
            if Path(name).name == "field_defaults.json" or "/images/" in "/" + name
        }
        manifest = f"{app}/app.json"
        if manifest in values:
            result[app] = combined(
                {
                    manifest: values[manifest],
                    **{k: v for k, v in shared.items() if "/images/" in "/" + k},
                }
            )
        for source in folder.glob("*.w4gl"):
            validate_name(source.stem)
            inputs = dict(shared)
            for suffix in SUFFIXES:
                name = source.with_suffix(suffix).relative_to(root).as_posix()
                if name in values:
                    inputs[name] = values[name]
            result[f"{app}/{source.stem}"] = combined(inputs)
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
            except (ValueError, KeyError, TypeError) as ex:
                raise ProjectError(
                    "Invalid transfer ledger; move .openroad/transfers.json aside to start a full transfer"
                ) from ex

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"version": 1, "target": self.target, "entries": self.entries},
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


def copy_inputs(
    root: Path, app: str, destination: Path, components: set[str] | None = None
) -> None:
    for path in source_files(root, app):
        if (
            components is not None
            and path.parent == root / app
            and any(path.name.endswith(suffix) for suffix in SUFFIXES)
            and path.name.split(".", 1)[0] not in components
        ):
            continue
        target_path = destination / path.relative_to(root)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target_path)


def prepare(
    source: Path,
    destination: Path,
    names: list[str],
    *,
    application: bool,
    result: Result,
) -> list[str]:
    accepted: list[str] = []
    with etree.xmlfile(str(destination), encoding="UTF-8") as output:
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
) -> None:
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
    ledger = Ledger(root, connection)
    report("Hashing local source")
    local = hashes(root)
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
        return result
    remote = inventory(connection)
    pending = sorted({key.split("/")[0] for key in changed})
    planned = set(pending)
    # Create included source applications first; independent applications continue after failure.
    from .project import read_json

    dependencies: dict[str, set[str]] = {}
    for app in pending:
        try:
            metadata = read_json(root / app / "app.json")
            dependencies[app] = {
                item if isinstance(item, str) else item["name"]
                for item in metadata.get("included_applications", [])
                if isinstance(item, str) or not item.get("image")
            }
        except Exception as ex:
            result.failed[app] = str(ex)
    pending = [app for app in pending if app in dependencies]
    ordered: list[str] = []
    remaining = set(pending)
    while remaining:
        ready = sorted(app for app in remaining if not (dependencies[app] & remaining))
        if not ready:
            for app in remaining:
                result.failed[app] = "Cyclic source application includes"
            break
        ordered.extend(ready)
        remaining.difference_update(ready)
    available = {key for key in remote if "/" not in key}
    compilation: list[tuple[str, str]] = []
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
                snapshot = work / "source"
                create = app.casefold() not in {name.casefold() for name in available}
                copy_inputs(
                    root,
                    app,
                    snapshot,
                    None
                    if create or app in selected
                    else {key.split("/")[1] for key in selected if "/" in key},
                )
                captured = hashes(snapshot, [app])
                folder = snapshot / app
                names = (
                    sorted(p.stem for p in folder.glob("*.w4gl"))
                    if create
                    else [key.split("/")[1] for key in selected if "/" in key]
                )
                if create or app in selected:
                    names = sorted(p.stem for p in folder.glob("*.w4gl"))
                    submitted = work / "application.xml"
                    accepted = prepare(
                        folder, submitted, names, application=True, result=result
                    )
                    if dry_run:
                        result.succeeded.extend(accepted)
                        available.add(app)
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
                                connection, root, ledger, completed, captured, result
                            )
                            compilation.extend(
                                (app, key.split("/")[1])
                                for key in completed
                                if key in result.succeeded
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
                    available.add(app)
                    post_import(connection, root, ledger, accepted, captured, result)
                    compilation.extend(
                        (app, key.split("/")[1])
                        for key in accepted
                        if "/" in key and key in result.succeeded
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
                                connection, root, ledger, accepted, captured, result
                            )
                            if key != app and key in result.succeeded:
                                compilation.append((app, key.split("/")[1]))
                        except Exception as ex:
                            result.failed[key] = str(ex)
                shutil.rmtree(folder, ignore_errors=True)
            except Exception as ex:
                result.failed[app] = str(ex)
                for key in selected:
                    if key != app and key not in result.failed:
                        result.skipped[key] = "Application import failed"
            report("Uploading applications", index, len(ordered))
        if compile and compilation and not dry_run:
            from .compiler import compile_source

            for app, name in compilation:
                try:
                    (work / "compile.log").unlink(missing_ok=True)
                    outcome = compile_source(
                        connection, app, name, work / "compile.log"
                    )
                    if not outcome.success:
                        raise ProjectError(outcome.diagnostics())
                except Exception as ex:
                    result.failed[f"{app}/{name}"] = (
                        f"Source imported; compilation failed: {ex}"
                    )
    if not dry_run:
        refresh_tokens(connection, ledger, result)
    return result


@validation_scope()
@resolution_scope()
def pull(
    connection: OpenRoadConnection,
    root: Path,
    *,
    full: bool = False,
    dry_run: bool = False,
) -> Result:
    ledger = Ledger(root, connection)
    report("Reading database change tokens")
    remote = inventory(connection)
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

    with prefetched_exports(names, connection.export_workers, backup) as exports:
        for index, (app, xml) in enumerate(exports, 1):
            if app in export_errors:
                result.failed[app] = export_errors[app]
                continue
            folder = root / app
            folder.mkdir(parents=True, exist_ok=True)
            writer = AssetWriter(folder)
            accepted: list[str] = []
            try:
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
                            staged.write_text(payload)
                            staged.replace(folder / "app.json")
                        else:
                            project_component_files(
                                native, folder, writer, None, parent_styles=styles
                            )
                        accepted.append(key)
                    except Exception as ex:
                        result.failed[key] = str(ex)
                    converted += 1
                    report(f"Converting {app}", converted, count)
                local = hashes(root, [app])
                for key in accepted:
                    token = remote[catalog_keys[key.casefold()]]
                    old = identities.get(("/" in key, identity(token)))
                    if old == key:
                        old = None
                    if old:
                        if "/" in old:
                            for suffix in SUFFIXES:
                                previous = root / (old + suffix)
                                current = root / (key + suffix)
                                if previous.exists() and (
                                    not current.exists()
                                    or not previous.samefile(current)
                                ):
                                    previous.unlink()
                        else:
                            previous = root / old / "app.json"
                            current = root / key / "app.json"
                            if previous.exists() and not previous.samefile(current):
                                previous.unlink()
                        # Leave unrelated files in an old application folder untouched.
                        ledger.entries.pop(old)
                    ledger.record(key, local[key], token)
                    identities[("/" in key, identity(token))] = key
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
    ledger = Ledger(root, connection)
    report("Hashing local source")
    local = hashes(root)
    report("Reading database change tokens")
    remote = inventory(connection)
    apps = {app.casefold() for app in app_names(root, ledger)}
    prior = {key.casefold(): value for key, value in ledger.entries.items()}
    return {
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

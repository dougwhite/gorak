"""Explicit disk-to-database sync with preflight and retained import artifacts."""

import tomllib
from pathlib import Path
from uuid import uuid4

from lxml import etree

from .connection import OpenRoadConnection
from .export import (
    backup_application_xml,
    backup_component_xml,
    read_applications,
    read_components,
)
from .field_defaults import effective_defaults, read_defaults
from .import_backend import import_component_xml
from .importer import component_tree, import_component, signature, validate_name
from .parser import (
    encode_w4gl,
    encode_wml,
    parse_application_xml,
    parse_component_node,
    parse_w4gl,
    split_w4gl,
)
from .project import ProjectError
from .xml_writer import document, new_application, new_component


def push_project(
    connection: OpenRoadConnection, root: Path, dry_run: bool = False
) -> str:
    directory = root / ".openroad" / "pushes"
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "push.lock"
    try:
        handle = lock.open("x")
    except FileExistsError as ex:
        raise ProjectError(f"Another push may be active; inspect {lock}") from ex
    try:
        with handle:
            return _push_project(connection, root, dry_run)
    finally:
        lock.unlink()


def _push_project(
    connection: OpenRoadConnection, root: Path, dry_run: bool = False
) -> str:
    """Preflight every disk component before creating or updating database objects."""
    operation = root / ".openroad" / "pushes" / uuid4().hex
    operation.mkdir(parents=True)
    known = {app.name.casefold() for app in read_applications(connection)}
    creations: dict[str, tuple[str, bytes, list[Path]]] = {}
    edits: list[tuple[str, str]] = []
    app_updates: dict[str, bytes] = {}
    prepared_edits: dict[tuple[str, str], Path] = {}
    snapshots: dict[Path, bytes] = {}
    dependencies: dict[str, set[str]] = {}
    folders = sorted(
        p.parent for p in root.glob("*/app.json") if not p.parent.name.startswith(".")
    )
    if len({p.name.casefold() for p in folders}) != len(folders):
        raise ProjectError("Application names collide ignoring case")
    for folder in folders:
        app = folder.name
        validate_name(app)
        paths = sorted(folder.glob("*.w4gl"))
        if len({p.stem.casefold() for p in paths}) != len(paths):
            raise ProjectError(f"Component names collide ignoring case: {app}")
        for path in [folder / "app.json", *paths]:
            snapshots[path] = path.read_bytes()
        if app.casefold() not in known:
            # Missing previously exported apps are deletions/conflicts, not creations.
            if (root / ".openroad" / app).exists():
                raise ProjectError(
                    f"Previously exported application is missing from database: {app}"
                )
            node = new_application(folder)
            nodes = [new_component(path) for path in paths]
            start = node.findtext("procstart")
            if start and start.casefold() not in {p.stem.casefold() for p in paths}:
                raise ProjectError(f"Starting component is missing: {app}/{start}")
            dependencies[app.casefold()] = {
                row.findtext("appname", "").casefold()
                for row in node.findall("included_apps/row")
                if not row.findtext("imgfilename")
            }
            creations[app] = ("-", document([node, *nodes]), paths)
            continue
        app_cache = root / ".openroad" / app / f"{app}.xml"
        if app_cache.is_file():
            previous_app = parse_application_xml(etree.parse(str(app_cache)))
            disk_app = parse_application_xml(
                etree.fromstring(document([new_application(folder)]))
            )
            if (
                previous_app.application != disk_app.application
                or previous_app.included_applications != disk_app.included_applications
            ):
                before = operation / f"{app}-before.xml"
                backup_application_xml(connection, app, before)
                parser = etree.XMLParser(
                    resolve_entities=False, no_network=True, strip_cdata=False
                )
                tree = etree.parse(str(before), parser)
                original_node = etree.parse(str(app_cache), parser).find("APPLICATION")
                current_node = tree.find("APPLICATION")
                if (
                    original_node is None
                    or current_node is None
                    or signature(original_node) != signature(current_node)
                ):
                    raise ProjectError(
                        f"Database application metadata changed since export: {app}"
                    )
                replacement = new_application(folder)
                managed = {
                    "versshortremarks",
                    "included_apps",
                    "procstart",
                    "databasename",
                    "database_type",
                }
                for child in list(current_node):
                    if child.tag in managed:
                        current_node.remove(child)
                current_node.extend(replacement)
                order = [
                    "versshortremarks",
                    "extension",
                    "taggedvalues",
                    "included_apps",
                    "procstart",
                    "databasename",
                    "database_type",
                    "commandline",
                    "windowicon",
                    "globalsfile",
                    "appflags",
                ]
                if any(child.tag not in order for child in current_node):
                    raise ProjectError(f"Unknown application XML metadata: {app}")
                current_node[:] = sorted(
                    current_node, key=lambda child: order.index(str(child.tag))
                )
                app_updates[app] = bytes(
                    etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
                )
        current = {c.name.casefold() for c in read_components(connection, app)}
        for path in paths:
            name = path.stem
            validate_name(name)
            cache = root / ".openroad" / app
            candidates = sorted(
                [
                    p
                    for p in [cache / f"{name}.xml", cache / f"{app}.xml"]
                    if p.is_file()
                ],
                key=lambda p: p.stat().st_mtime_ns,
                reverse=True,
            )
            baseline = None
            for candidate in candidates:
                try:
                    baseline = parse_component_node(component_tree(candidate, name))
                    break
                except ProjectError:
                    continue
            if name.casefold() not in current:
                if baseline is not None:
                    raise ProjectError(
                        f"Previously exported component is missing from database: {app}/{name}"
                    )
                creations[f"{app}/{name}"] = (
                    name,
                    document([new_component(path)]),
                    [path],
                )
            elif baseline is None:
                raise ProjectError(
                    f"Existing component needs an export baseline: {app}/{name}"
                )
            else:
                edited = parse_w4gl(path.read_text(), name)
                if baseline.type == "framesource":
                    frame_defaults = edited.props.get("fielddefaults", {})
                    original_defaults = baseline.props.get("fielddefaults", {})
                    if original_defaults != effective_defaults(
                        read_defaults(root / "field_defaults.json"),
                        read_defaults(folder / "field_defaults.json"),
                        frame_defaults,
                    ):
                        raise ProjectError(
                            f"Frame defaults changed; push not supported: {app}/{name}"
                        )
                    baseline.props.pop("fielddefaults", None)
                    edited.props.pop("fielddefaults", None)
                    markup = path.with_suffix(".wml")
                    if (
                        not markup.is_file()
                        or markup.read_text().strip()
                        != (encode_wml(baseline) or "").strip()
                    ):
                        raise ProjectError(
                            f"Frame markup changed; push not supported: {app}/{name}"
                        )
                    if (
                        edited.props != baseline.props
                        or edited.script != baseline.script
                        or edited.type != baseline.type
                    ):
                        raise ProjectError(
                            f"Frame edits are not supported: {app}/{name}"
                        )
                    continue
                if edited.script == baseline.script and tomllib.loads(
                    split_w4gl(path.read_text())[0]
                ) == tomllib.loads(split_w4gl(encode_w4gl(baseline))[0]):
                    continue
                # The importer also rejects metadata edits and checks database drift.
                prepared_edits[(app, name)] = (
                    import_component(connection, root, app, name, dry_run=True)
                    / "submitted.xml"
                )
                edits.append((app, name))
    for app, payload in list(app_updates.items()):
        tree_root = etree.fromstring(payload)
        sources = []
        for edited_app, name in list(edits):
            if edited_app == app:
                existing = next(
                    n for n in tree_root.findall("COMPONENT") if n.get("name") == name
                )
                tree_root.replace(
                    existing, component_tree(prepared_edits[(app, name)], name)
                )
                edits.remove((app, name))
        for key in list(creations):
            if key.startswith(app + "/"):
                _, xml, paths = creations.pop(key)
                tree_root.extend(etree.fromstring(xml))
                sources.extend(paths)
        start = tree_root.findtext("APPLICATION/procstart")
        if start and start.casefold() not in {
            str(node.get("name", "")).casefold()
            for node in tree_root.findall("COMPONENT")
        }:
            raise ProjectError(f"Starting component is missing: {app}/{start}")
        creations[app] = (
            "-",
            bytes(etree.tostring(tree_root, encoding="UTF-8", xml_declaration=True)),
            sources,
        )
        dependencies[app.casefold()] = {
            row.findtext("appname", "").casefold()
            for row in tree_root.findall("APPLICATION/included_apps/row")
            if not row.findtext("imgfilename")
        }
    ordered: list[str] = []
    pending = dict(creations)
    available = set(known)
    while pending:
        ready = [
            key
            for key in pending
            if dependencies.get(key.casefold(), set()) <= available
        ]
        if not ready:
            raise ProjectError(
                "New applications have missing or cyclic source includes"
            )
        for key in ready:
            ordered.append(key)
            pending.pop(key)
            if "/" not in key:
                available.add(key.casefold())
    for index, key in enumerate(ordered):
        (operation / f"{index}-submitted.xml").write_bytes(creations[key][1])
    if dry_run:
        return f"Push dry run: {len(creations) - len(app_updates)} creations, {len(app_updates)} application updates, {len(edits)} script updates. XML: {operation}"
    for path, content in snapshots.items():
        if path.read_bytes() != content:
            raise ProjectError(f"Local source changed during push preflight: {path}")
    try:
        for index, key in enumerate(ordered):
            component, _, sources = creations[key]
            app = key.split("/")[0]
            submitted = operation / f"{index}-submitted.xml"
            if app in app_updates:
                latest = operation / f"{app}-latest.xml"
                backup_application_xml(connection, app, latest)
                if signature(etree.parse(str(latest)).getroot()) != signature(
                    etree.parse(str(operation / f"{app}-before.xml")).getroot()
                ):
                    raise ProjectError(
                        f"Database application changed during push: {app}"
                    )
            import_component_xml(
                connection,
                app,
                component,
                submitted,
                operation / f"{index}-import.log",
                create=app not in app_updates,
            )
            after = operation / f"{index}-after.xml"
            if component == "-":
                backup_application_xml(connection, app, after)
            else:
                backup_component_xml(connection, app, component, after)
            if component == "-":
                exported = parse_application_xml(etree.parse(str(after)))
                requested = parse_application_xml(etree.parse(str(submitted)))
                if (
                    exported.application != requested.application
                    or exported.included_applications != requested.included_applications
                ):
                    raise ProjectError(
                        f"Created application metadata verification failed: {app}"
                    )
            if app in app_updates:
                before_tree = etree.parse(str(submitted))
                for node in before_tree.findall("COMPONENT"):
                    name = str(node.get("name"))
                    if signature(component_tree(after, name)) != signature(node):
                        raise ProjectError(
                            f"Existing component changed during application update: {app}/{name}"
                        )
            for source in sources:
                actual = parse_component_node(component_tree(after, source.stem))
                expected = parse_component_node(new_component(source))
                if (
                    actual.script != expected.script
                    or actual.type != expected.type
                    or actual.props != expected.props
                ):
                    raise ProjectError(
                        f"Created component verification failed: {source.stem}"
                    )
            cache = root / ".openroad" / app
            cache.mkdir(exist_ok=True)
            target = cache / f"{app if component == '-' else component}.xml"
            target.write_bytes(after.read_bytes())
        for app, name in edits:
            import_component(connection, root, app, name)
    except Exception as ex:
        raise ProjectError(
            f"Push stopped; earlier operations may have succeeded. Artifacts: {operation}\n{ex}"
        ) from ex
    return f"Push complete: {len(creations) - len(app_updates)} creations, {len(app_updates)} application updates, {len(edits)} script updates. Artifacts: {operation}"

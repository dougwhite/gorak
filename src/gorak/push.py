"""Explicit disk-to-database sync with preflight and retained import artifacts."""

import json
from pathlib import Path
from uuid import uuid4

from lxml import etree

from .connection import OpenRoadConnection
from .errors import SourceVerificationError
from .export import (
    backup_application_xml,
    backup_component_xml,
    read_applications,
    read_components,
)
from .import_backend import import_component_xml
from .importer import component_tree, import_component, signature, validate_name
from .parser import (
    parse_application_xml,
    parse_component_node,
)
from .portable_source import restore_application, restore_component
from .project import ProjectError, read_json
from .project_lock import open_lock
from .readable_source import is_complete
from .safe_pull import apply_files, fingerprint
from .xml_writer import document, new_application, new_component


def push_project(
    connection: OpenRoadConnection, root: Path, dry_run: bool = False
) -> str:
    if (root / ".openroad/push-pending.json").exists():
        raise ProjectError(
            "An interrupted push requires recovery; inspect .openroad/push-pending.json"
        )
    directory = root / ".openroad" / "pushes"
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "push.lock"
    try:
        handle = open_lock(lock, "push")
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
    initial = fingerprint(root)
    source_snapshot = {
        k: v for k, v in initial.items() if not k.startswith(".openroad/")
    }

    def check_source() -> None:
        current = {
            k: v for k, v in fingerprint(root).items() if not k.startswith(".openroad/")
        }
        if current != source_snapshot:
            raise ProjectError(
                "Local project changed during push; reconcile before retrying"
            )

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
        auxiliary = list(folder.glob("*.wml"))
        auxiliary.extend(
            p
            for p in [root / "field_defaults.json", folder / "field_defaults.json"]
            if p.is_file()
        )
        for path in [folder / "app.json", *paths, *auxiliary]:
            snapshots[path] = path.read_bytes()
        if app.casefold() not in known:
            # Missing previously exported apps are deletions/conflicts, not creations.
            if any((root / ".openroad" / app).glob("*.xml")):
                raise ProjectError(
                    f"Previously exported application is missing from database: {app}"
                )
            node = restore_application(folder)
            nodes = [restore_component(path) for path in paths]
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
            complete_app = read_json(folder / "app.json").get("source_format") == 2
            app_source_changed = complete_app and signature(
                etree.parse(str(app_cache)).find("APPLICATION")
            ) != signature(new_application(folder))
            if (
                app_source_changed
                or previous_app.application != disk_app.application
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
                if complete_app:
                    managed = {str(child.tag) for child in current_node}
                    current_node.attrib.clear()
                    current_node.attrib.update(replacement.attrib)
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
                from copy import deepcopy

                from .portable_source import overlay_component

                baseline_node = component_tree(candidate, name)
                overlaid = overlay_component(deepcopy(baseline_node), path)
                if signature(overlaid) == signature(baseline_node):
                    continue
                # The importer validates the overlay and checks database drift.
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
    check_source()
    if dry_run:
        return f"Push dry run: {len(creations) - len(app_updates)} creations, {len(app_updates)} application updates, {len(edits)} component updates. XML: {operation}"
    for path, content in snapshots.items():
        if path.read_bytes() != content:
            raise ProjectError(f"Local source changed during push preflight: {path}")
    if not ordered and not edits:
        from .compiler import compile_pending

        return "\n".join(
            [
                f"Push complete: no changes. Artifacts: {operation}",
                *compile_pending(connection, root, operation),
            ]
        )
    # Retain the baseline before any database mutation so a retry can distinguish
    # accepted submissions from independent database edits after a lost response.
    for relative in initial:
        if relative.startswith(".openroad/"):
            backup = operation / "baseline" / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes((root / relative).read_bytes())
    (operation / "plan.json").write_text(
        json.dumps({"creations_or_updates": ordered, "script_updates": edits}, indent=2)
    )
    # Retain every submitted component under this operation before the first write.
    for (app, name), prepared_path in prepared_edits.items():
        retained = operation / "submitted" / app / f"{name}.xml"
        retained.parent.mkdir(parents=True, exist_ok=True)
        retained.write_bytes(prepared_path.read_bytes())
    from .compiler import queue_compilation

    targets = list(edits)
    for key in ordered:
        app = key.split("/")[0]
        tree = etree.fromstring(creations[key][1])
        targets.extend((app, str(n.get("name"))) for n in tree.findall("COMPONENT"))
    queue_compilation(root, targets)
    pending_marker = root / ".openroad/push-pending.json"
    from .push_retry import write_record

    write_record(pending_marker, {"operation": str(operation), "state": "retryable"})
    cache_updates: dict[Path, bytes] = {}
    installing = False
    try:
        for index, key in enumerate(ordered):
            check_source()
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
            else:
                latest_apps = {a.name.casefold() for a in read_applications(connection)}
                if component == "-" and app.casefold() in latest_apps:
                    raise ProjectError(f"Application appeared during push: {app}")
                if component != "-":
                    if app.casefold() not in latest_apps:
                        raise ProjectError(
                            f"Application disappeared during push: {app}"
                        )
                    if component.casefold() in {
                        c.name.casefold() for c in read_components(connection, app)
                    }:
                        raise ProjectError(
                            f"Component appeared during push: {app}/{component}"
                        )
            check_source()
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
                actual_app = etree.parse(str(after)).find("APPLICATION")
                expected_app = etree.parse(str(submitted)).find("APPLICATION")
                if (
                    actual_app is None
                    or expected_app is None
                    or (
                        read_json(root / app / "app.json").get("source_format") == 2
                        and signature(actual_app) != signature(expected_app)
                    )
                ):
                    raise SourceVerificationError(
                        f"Application source verification failed: {app}"
                    )
                exported = parse_application_xml(etree.parse(str(after)))
                requested = parse_application_xml(etree.parse(str(submitted)))
                if (
                    exported.application != requested.application
                    or exported.included_applications != requested.included_applications
                ):
                    raise SourceVerificationError(
                        f"Created application metadata verification failed: {app}"
                    )
            if app in app_updates:
                before_tree = etree.parse(str(submitted))
                for node in before_tree.findall("COMPONENT"):
                    name = str(node.get("name"))
                    actual_node = component_tree(after, name)
                    normalized = None
                    if (app, name) in prepared_edits:
                        from .frame_geometry import normalized_markup

                        normalized = normalized_markup(
                            node,
                            actual_node,
                            complete=is_complete(root / app / f"{name}.w4gl"),
                        )
                    if normalized is not None:
                        cache_updates[root / app / f"{name}.wml"] = normalized.encode()
                    if signature(actual_node) != signature(node) and normalized is None:
                        raise SourceVerificationError(
                            f"Existing component changed during application update: {app}/{name}"
                        )
            for source in sources:
                actual_node = component_tree(after, source.stem)
                expected_node = component_tree(submitted, source.stem)
                if is_complete(source):
                    from .frame_geometry import normalized_markup

                    normalized = normalized_markup(
                        expected_node, actual_node, complete=is_complete(source)
                    )
                    if normalized is not None:
                        cache_updates[source.with_suffix(".wml")] = normalized.encode()
                    if (
                        signature(actual_node) != signature(expected_node)
                        and normalized is None
                    ):
                        raise SourceVerificationError(
                            f"Portable XML verification failed: {source.stem}"
                        )
                if not is_complete(source):
                    from .contract_source import equivalent

                    if not equivalent(actual_node, expected_node):
                        raise SourceVerificationError(
                            f"Readable source verification failed: {source.stem}"
                        )
                actual = parse_component_node(actual_node)
                expected = parse_component_node(expected_node)
                if (
                    actual.script != expected.script
                    or actual.type != expected.type
                    or actual.props != expected.props
                ):
                    raise SourceVerificationError(
                        f"Created component verification failed: {source.stem}"
                    )
            cache = root / ".openroad" / app
            cache.mkdir(exist_ok=True)
            target = cache / f"{app if component == '-' else component}.xml"
            cache_updates[target] = after.read_bytes()
        for app, name in edits:
            check_source()
            imported = import_component(
                connection, root, app, name, advance_cache=False
            )
            cache_updates[root / ".openroad" / app / f"{name}.xml"] = (
                imported / "after.xml"
            ).read_bytes()
            normalized_path = imported / "normalized.wml"
            if normalized_path.exists():
                cache_updates[root / app / f"{name}.wml"] = normalized_path.read_bytes()
        check_source()
        installing = True
        apply_files(root, dict(cache_updates), operation, initial)
        installing = False
        (operation / "verified").write_text(
            "Push imports and source snapshot verified\n"
        )
        pending_marker.unlink()
    except Exception as ex:
        if installing or isinstance(ex, SourceVerificationError):
            from .push_retry import mark_recovery

            mark_recovery(root, operation)
        raise ProjectError(
            f"Push stopped; earlier operations may have succeeded. Artifacts: {operation}\n{ex}"
        ) from ex
    # Source is committed before compilation. A failed compiler cannot undo sync.
    from .compiler import compile_pending

    diagnostics = compile_pending(connection, root, operation)
    summary = f"Push complete: {len(creations) - len(app_updates)} creations, {len(app_updates)} application updates, {len(edits)} component updates. Artifacts: {operation}"
    return "\n".join([summary, *diagnostics])

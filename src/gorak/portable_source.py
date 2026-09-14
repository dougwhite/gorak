"""Readable reconstruction and explicit migration support for legacy companions."""

from copy import deepcopy
from pathlib import Path

from lxml import etree

from .field_defaults import effective_defaults, read_defaults
from .parser import (
    parse_component_node,
    parse_w4gl,
)
from .project import ProjectError

DIRECTORY = ".gorak-source"


def read_document(path: Path) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, strip_cdata=False)
    tree = etree.parse(str(path), parser)
    if tree.docinfo.doctype:
        raise ProjectError(f"Source XML must not contain a document type: {path}")
    return tree.getroot()


def write_companions(xml: Path, folder: Path) -> None:
    """Keep opaque source XML under version control alongside readable projections."""
    from .xml_writer import document

    root = read_document(xml)
    if any(node.tag not in {"APPLICATION", "COMPONENT"} for node in root):
        raise ProjectError(
            "Unsupported top-level XML source; cannot preserve it as companions"
        )
    directory = folder / DIRECTORY
    directory.mkdir(exist_ok=True)
    (directory / "format").write_text("1\n")
    (directory / "components").mkdir(exist_ok=True)
    application = root.find("APPLICATION")
    if application is not None:
        (directory / "application.xml").write_bytes(document([deepcopy(application)]))
    for node in root.findall("COMPONENT"):
        name = node.get("name", "")
        from .importer import validate_name

        validate_name(name)
        (directory / "components" / f"{name}.xml").write_bytes(
            document([deepcopy(node)])
        )


def cached_node(folder: Path, tag: str, name: str) -> etree._Element | None:
    """Read an older checkout baseline without mistaking exported source for new source."""
    cache = folder.parent / ".openroad" / folder.name
    files = sorted(
        cache.glob("*.xml"), key=lambda p: p.stat().st_mtime_ns, reverse=True
    )
    for path in files:
        root = read_document(path)
        matches = [
            n
            for n in root.findall(tag)
            if n.get("name", "").casefold() == name.casefold()
        ]
        if len(matches) > 1:
            raise ProjectError(f"Ambiguous cached source: {path}")
        if matches:
            return matches[0]
        # A newer full export authoritatively records component absence.
        if tag == "COMPONENT" and root.find("APPLICATION") is not None:
            return None
    return None


def legacy_component(path: Path) -> etree._Element:
    """Overlay readable edits over portable companions or legacy cached XML."""
    from .readable_source import decode_component, is_complete
    from .xml_writer import new_component

    if is_complete(path):
        return decode_component(path)
    companion = path.parent / DIRECTORY / "components" / f"{path.stem}.xml"
    if companion.is_file():
        if (companion.parent.parent / "format").read_text().strip() != "1":
            raise ProjectError("Unsupported portable source format")
        nodes = read_document(companion).findall("COMPONENT")
        if len(nodes) != 1 or nodes[0].get("name") != path.stem:
            raise ProjectError(f"Invalid component companion: {companion}")
        node = nodes[0]
    else:
        baseline = cached_node(path.parent, "COMPONENT", path.stem)
        if baseline is None:
            return new_component(path)
        node = baseline
    return overlay_component(node, path)


def overlay_component(node: etree._Element, path: Path) -> etree._Element:
    """Apply editable source to a supplied baseline, preserving opaque XML."""
    from .readable_source import decode_component, is_complete

    if is_complete(path):
        replacement = decode_component(path)
        for query in replacement.findall("queries"):
            replacement.remove(query)
        if replacement.get("name") != node.get("name") or replacement.get(
            "{http://www.w3.org/2001/XMLSchema-instance}type"
        ) != node.get("{http://www.w3.org/2001/XMLSchema-instance}type"):
            raise ProjectError(
                "Component identity or type cannot change during an edit"
            )
        node.attrib.clear()
        node.attrib.update(replacement.attrib)
        node.text = replacement.text
        node[:] = list(replacement)
        return node
    from .contract_source import decode_component as decode_contract
    from .contract_source import equivalent

    # A readable no-op must not replace transport-only XML serialization, such
    # as bitmap line wrapping. Queries are explicitly removed on re-encoding.
    try:
        unchanged = equivalent(decode_contract(path), node)
    except ProjectError:
        # A legacy baseline can retain source outside the standalone authoring
        # surface. The overlay below still validates every requested change.
        unchanged = False
    if node.find("queries") is None and unchanged:
        return node
    original = parse_component_node(node)
    text = path.read_text()
    edited = parse_w4gl(text, path.stem)
    defaults = original.props.get("fielddefaults", {})
    if original.type == "framesource":
        from .defaults_writer import overlay_defaults

        repo = read_defaults(path.parent.parent / "field_defaults.json")
        app = read_defaults(path.parent / "field_defaults.json")
        overrides = edited.props.get("fielddefaults", {})
        if "structure" in repo or "structure" in app:
            from .palette import decode, merge, upgrade_legacy
            from .xml_shapes import order_children

            inherited = merge(repo, app)
            normalized = upgrade_legacy(overrides, inherited, metadata=False)
            replacement = decode(merge(inherited, normalized))
            current_defaults = node.find("fielddefaults")
            if current_defaults is None:
                node.append(replacement)
                order_children(node, "framesource")
            else:
                node.replace(current_defaults, replacement)
        else:
            desired = effective_defaults(repo, app, overrides)
            if desired != defaults:
                overlay_defaults(node, desired)
    from .component_edits import overlay_metadata
    from .wml_writer import overlay_markup

    overlay_metadata(node, path)
    if original.markup is not None:
        overlay_markup(node, path.with_suffix(".wml"))

    return node


def legacy_application(folder: Path) -> etree._Element:
    """Preserve unknown app source properties while replacing represented metadata."""
    from .project import read_json
    from .xml_writer import new_application

    edited = new_application(folder)
    if read_json(folder / "app.json").get("source_format") == 2:
        return edited
    companion = folder / DIRECTORY / "application.xml"
    if companion.is_file():
        if (companion.parent / "format").read_text().strip() != "1":
            raise ProjectError("Unsupported portable source format")
        nodes = read_document(companion).findall("APPLICATION")
        if len(nodes) != 1 or nodes[0].get("name") != folder.name:
            raise ProjectError(f"Invalid application companion: {companion}")
        node = nodes[0]
    else:
        baseline = cached_node(folder, "APPLICATION", folder.name)
        if baseline is None:
            return edited
        node = baseline
    managed = {
        "versshortremarks",
        "included_apps",
        "procstart",
        "databasename",
        "database_type",
    }
    for child in list(node):
        if child.tag in managed:
            node.remove(child)
    node.extend(edited)
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
    if any(child.tag not in order for child in node):
        raise ProjectError(
            "Unknown application XML field order; cannot safely reconstruct"
        )
    node[:] = sorted(node, key=lambda child: order.index(str(child.tag)))
    return node


def restore_component(path: Path) -> etree._Element:
    """Reconstruct only from versioned readable files, never cached XML."""
    from .xml_writer import new_component

    return new_component(path)


def restore_application(folder: Path) -> etree._Element:
    """Reconstruct application metadata without cache or companion lookup."""
    from .xml_writer import new_application

    return new_application(folder)


def comparison_component(path: Path) -> etree._Element:
    """Preserve unrepresented baseline details for three-way comparison only."""
    from .readable_source import is_complete

    if not is_complete(path):
        baseline = cached_node(path.parent, "COMPONENT", path.stem)
        if baseline is not None:
            return overlay_component(deepcopy(baseline), path)
    return restore_component(path)


def comparison_application(folder: Path) -> etree._Element:
    from .parser import parse_application_xml
    from .project import read_json
    from .xml_writer import document

    desired = restore_application(folder)
    if read_json(folder / "app.json").get("source_format") == 2:
        return desired
    baseline = cached_node(folder, "APPLICATION", folder.name)
    if baseline is None:
        return desired
    old = parse_application_xml(etree.fromstring(document([baseline])))
    new = parse_application_xml(etree.fromstring(document([desired])))
    if (
        old.application == new.application
        and old.included_applications == new.included_applications
    ):
        return baseline
    managed = {
        "versshortremarks",
        "included_apps",
        "procstart",
        "databasename",
        "database_type",
    }
    for child in list(baseline):
        if child.tag in managed:
            baseline.remove(child)
    baseline.extend(desired)
    from .readable_source import APP_FIELDS

    order = [tag for tag, _ in APP_FIELDS.values()]
    baseline[:] = sorted(baseline, key=lambda child: order.index(str(child.tag)))
    return baseline

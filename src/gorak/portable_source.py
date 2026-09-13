"""Versioned XML source companions, independent of database synchronization state."""

import tomllib
from copy import deepcopy
from pathlib import Path

from lxml import etree

from .field_defaults import diff_defaults, effective_defaults, read_defaults
from .parser import (
    encode_w4gl,
    encode_wml,
    parse_component_node,
    parse_w4gl,
    split_w4gl,
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


def restore_component(path: Path) -> etree._Element:
    """Overlay script edits; refuse unimplemented changes to metadata or frame UI."""
    from .xml_writer import new_component

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
    original = parse_component_node(node)
    text = path.read_text()
    edited = parse_w4gl(text, path.stem)
    defaults = original.props.pop("fielddefaults", None)
    if isinstance(defaults, dict):
        parent = effective_defaults(
            read_defaults(path.parent.parent / "field_defaults.json"),
            read_defaults(path.parent / "field_defaults.json"),
            {},
        )
        override = diff_defaults(parent, defaults)
        if override:
            original.props["fielddefaults"] = override
        supplied = edited.props.get("fielddefaults", {})
        if effective_defaults(parent, {}, supplied) != defaults:
            raise ProjectError(f"Field default edits are not supported: {path}")
    if original.type != edited.type or tomllib.loads(
        split_w4gl(encode_w4gl(original))[0]
    ) != tomllib.loads(split_w4gl(text)[0]):
        raise ProjectError(
            f"Portable component metadata edits are not supported: {path}"
        )
    markup = encode_wml(original)
    if markup is not None:
        wml = path.with_suffix(".wml")
        if not wml.is_file() or wml.read_text().strip() != markup.strip():
            raise ProjectError(f"Frame markup edits are not supported: {path}")
    if edited.script != original.script:
        script = node.find("script")
        if script is None or edited.script is None:
            raise ProjectError(f"Cannot add or remove a script section: {path}")
        previous = script.text or ""
        leading = previous[: len(previous) - len(previous.lstrip())]
        trailing = previous[len(previous.rstrip()) :]
        script.text = etree.CDATA(leading + edited.script + trailing)
    return node


def restore_application(folder: Path) -> etree._Element:
    """Preserve unknown app source properties while replacing represented metadata."""
    from .xml_writer import new_application

    edited = new_application(folder)
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

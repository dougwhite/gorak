"""Generate OpenROAD XML for new applications and script components."""

import re
from pathlib import Path

from lxml import etree

from .importer import validate_name
from .parser import NS
from .project import ProjectError, read_json
from .xml_text import set_text


def scalar(parent: etree._Element, name: str, value: str) -> None:
    set_text(etree.SubElement(parent, name), value, cdata=True)


def datatype(row: etree._Element, declaration: str) -> None:
    # Preserve embedded legacy control characters; do not silently repair types.
    identifier = r"[A-Za-z_][A-Za-z0-9_\x00-\x08\x0b\x0c\x0e-\x1f]*"
    type_name = (
        rf"(?:{identifier}!{identifier}|LONG BYTE|{identifier}(?:\(\d+(?:,\s*\d+)?\))?)"
    )
    match = re.fullmatch(
        rf"(ARRAY OF )?({type_name})( NOT NULL)?",
        declaration,
        re.IGNORECASE,
    )
    if not match:
        raise ProjectError(f"Unsupported type declaration: {declaration!r}")
    scalar(row, "datatype", match[2].lower())
    if match[1]:
        scalar(row, "isarray", "1")
    from .member_declarations import reference_type

    if not match[3] or reference_type(match[2], bool(match[1])):
        scalar(row, "isnullable", "1")


def new_component(path: Path) -> etree._Element:
    from .contract_source import decode_component

    return decode_component(path)


def new_application(path: Path) -> etree._Element:
    validate_name(path.name)
    metadata = read_json(path / "app.json")
    fields = {
        "starting_component": "procstart",
        "description": "versshortremarks",
        "database_name": "databasename",
        "database_type": "database_type",
        "appflags": "appflags",
    }
    if set(metadata) - {*fields, "included_applications", "window_icon"}:
        raise ProjectError(f"Unsupported application metadata: {path}")
    node = etree.Element("APPLICATION", name=path.name)
    for key, tag in fields.items():
        value = metadata.get(key, "")
        if not isinstance(value, str):
            raise ProjectError(f"Application {key} must be a string")
        if value:
            scalar(node, tag, value)
    if metadata.get("window_icon"):
        from .image_assets import encode_icon

        scalar(
            etree.SubElement(node, "windowicon"),
            "obj_encoded",
            encode_icon(path, metadata["window_icon"]),
        )
    includes = metadata.get("included_applications", [])
    if not isinstance(includes, list):
        raise ProjectError("included_applications must be an array")
    container = etree.SubElement(node, "included_apps")
    for entry in [{"name": "core", "image": "core.plb"}, *includes]:
        if isinstance(entry, str):
            entry = {"name": entry}
        if (
            not isinstance(entry, dict)
            or set(entry) - {"name", "image"}
            or not isinstance(entry.get("name"), str)
        ):
            raise ProjectError("Invalid included application")
        validate_name(entry["name"])
        if "image" in entry and not isinstance(entry["image"], str):
            raise ProjectError("Included image must be a string")
        if len(container) and entry["name"].casefold() == "core":
            continue
        index = len(container)
        row = etree.SubElement(container, "row")
        if index:
            scalar(row, "sequence", str(index))
        scalar(row, "appname", entry["name"])
        scalar(row, "version", "-1")
        if "image" in entry:
            if not isinstance(entry["image"], str):
                raise ProjectError("Included image must be a string")
            scalar(row, "imgfilename", entry["image"])
    scalar(container, "row_class", "inclapp")
    order = [
        "versshortremarks",
        "included_apps",
        "procstart",
        "databasename",
        "database_type",
        "windowicon",
        "appflags",
    ]
    node[:] = sorted(node, key=lambda child: order.index(str(child.tag)))
    return node


def document(nodes: list[etree._Element]) -> bytes:
    root = etree.Element("OPENROAD", nsmap=NS)
    root.extend(nodes)
    return bytes(etree.tostring(root, encoding="UTF-8", xml_declaration=True))

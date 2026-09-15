"""Generate OpenROAD XML for new applications and script components."""

import re
from pathlib import Path

from lxml import etree

from .importer import validate_name
from .parser import NS
from .project import ProjectError, read_json


def scalar(parent: etree._Element, name: str, value: str) -> None:
    etree.SubElement(parent, name).text = value


def datatype(row: etree._Element, declaration: str) -> None:
    match = re.fullmatch(
        r"(ARRAY OF )?([A-Za-z_][A-Za-z0-9_]*(?:\(\d+(?:,\s*\d+)?\))?)( NOT NULL)?",
        declaration,
        re.IGNORECASE,
    )
    if not match:
        raise ProjectError(f"Unsupported type declaration: {declaration!r}")
    scalar(row, "datatype", match[2].lower())
    if match[1]:
        scalar(row, "isarray", "1")
    if not match[3]:
        scalar(row, "isnullable", "1")


def new_component(path: Path) -> etree._Element:
    from .readable_source import decode_component, is_complete

    if is_complete(path):
        node = decode_component(path)
        for query in node.findall("queries"):
            node.remove(query)
        return node
    from .contract_source import decode_component as decode_contract

    return decode_contract(path)


def new_application(path: Path) -> etree._Element:
    validate_name(path.name)
    metadata = read_json(path / "app.json")
    if metadata.get("source_format") == 2:
        from .readable_source import decode_application

        return decode_application(path)
    fields = {
        "starting_component": "procstart",
        "description": "versshortremarks",
        "database_name": "databasename",
        "database_type": "database_type",
    }
    if set(metadata) - {*fields, "included_applications"}:
        raise ProjectError(f"Unsupported application metadata: {path}")
    node = etree.Element("APPLICATION", name=path.name)
    for key, tag in fields.items():
        value = metadata.get(key, "")
        if not isinstance(value, str):
            raise ProjectError(f"Application {key} must be a string")
        if value:
            scalar(node, tag, value)
    includes = metadata.get("included_applications", [])
    if not isinstance(includes, list):
        raise ProjectError("included_applications must be an array")
    container = etree.SubElement(node, "included_apps")
    for index, entry in enumerate([{"name": "core", "image": "core.plb"}, *includes]):
        if isinstance(entry, str):
            entry = {"name": entry}
        if (
            not isinstance(entry, dict)
            or set(entry) - {"name", "image"}
            or not isinstance(entry.get("name"), str)
        ):
            raise ProjectError("Invalid included application")
        validate_name(entry["name"])
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
    ]
    node[:] = sorted(node, key=lambda child: order.index(str(child.tag)))
    return node


def document(nodes: list[etree._Element]) -> bytes:
    root = etree.Element("OPENROAD", nsmap=NS)
    root.extend(nodes)
    return bytes(etree.tostring(root, encoding="UTF-8", xml_declaration=True))

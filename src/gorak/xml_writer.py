"""Generate OpenROAD XML for new applications and script components."""

import re
import tomllib
from pathlib import Path

from lxml import etree

from .importer import validate_name
from .parser import NS, parse_w4gl, split_w4gl
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
        return decode_component(path)
    validate_name(path.stem)
    text = path.read_text()
    component = parse_w4gl(text, path.stem)
    metadata = tomllib.loads(split_w4gl(text)[0])
    if component.type not in {"proc4glsource", "classsource"}:
        raise ProjectError(f"New component type is not supported: {component.type}")
    if component.script is None:
        raise ProjectError(f"Missing === script section: {path}")
    allowed = {component.type, "attributes", "methods"}
    if set(metadata) - allowed:
        raise ProjectError(f"Unsupported component metadata: {path}")
    node = etree.Element("COMPONENT", name=component.name, nsmap=NS)
    node.set(f"{{{NS['xsi']}}}type", component.type)
    allowed_props = (
        {"datatype", "isnullable", "isarray", "versshortremarks"}
        if component.type == "proc4glsource"
        else {"superclass", "versshortremarks"}
    )
    for key, value in metadata[component.type].items():
        if key not in allowed_props or not isinstance(value, (str, int, bool)):
            raise ProjectError(f"Unsupported new component property: {key}")
        scalar(node, key, str(int(value)) if isinstance(value, bool) else str(value))
    scalar(node, "script", "")
    node.find("script").text = etree.CDATA(component.script)
    for table, row_class in [
        ("attributes", "attributeobject"),
        ("methods", "methodobject"),
    ]:
        if table not in metadata:
            continue
        if component.type != "classsource" or not isinstance(metadata[table], dict):
            raise ProjectError(f"Invalid {table} table")
        container = etree.SubElement(node, table)
        for name, declaration in metadata[table].items():
            validate_name(name)
            if not isinstance(declaration, str):
                raise ProjectError(f"Invalid declaration for {name}")
            row = etree.SubElement(container, "row")
            scalar(row, "displayname", name)
            if table == "methods":
                match = re.fullmatch(
                    r"(PRIVATE )?METHOD(?: RETURNING (.+))?", declaration
                )
                if not match:
                    raise ProjectError(f"Unsupported method declaration: {declaration}")
                if match[1]:
                    scalar(row, "isprivate", "1")
                declaration = match[2] or ""
            if declaration:
                datatype(row, declaration)
        for row in container:
            order = ["displayname", "datatype", "isarray", "isnullable", "isprivate"]
            row[:] = sorted(row, key=lambda child: order.index(str(child.tag)))
        scalar(container, "row_class", row_class)
    if component.type == "classsource" and node.find("superclass") is None:
        raise ProjectError("A new class requires superclass metadata")
    order = [
        "versshortremarks",
        "superclass",
        "script",
        "datatype",
        "isarray",
        "isnullable",
        "attributes",
        "methods",
    ]
    node[:] = sorted(node, key=lambda child: order.index(str(child.tag)))
    return node


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

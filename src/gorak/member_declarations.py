"""Lossless member declarations, with structured values only for extra metadata."""

import re
from typing import Any

from lxml import etree

from .errors import ProjectError
from .xml_text import is_text_node, set_text, text_value

# Other names denote built-in objects or application-defined classes. Objects and
# arrays are intrinsically nullable, independently of their initialization mode.
SCALARS = {
    "integer",
    "integer1",
    "integer2",
    "integer4",
    "integer8",
    "int",
    "int1",
    "int2",
    "int4",
    "int8",
    "smallint",
    "bigint",
    "tinyint",
    "float",
    "float4",
    "float8",
    "real",
    "double precision",
    "decimal",
    "numeric",
    "money",
    "date",
    "ingresdate",
    "ansidate",
    "time",
    "timestamp",
    "interval",
    "char",
    "c",
    "varchar",
    "text",
    "long varchar",
    "nchar",
    "nvarchar",
    "long nvarchar",
    "byte",
    "varbyte",
    "long byte",
    "boolean",
}
COMMON = {
    "displayname",
    "datatype",
    "isarray",
    "isnullable",
    "isprivate",
    "remark",
    "taggedvalues",
}


def reference_type(datatype: str, array: bool = False) -> bool:
    return array or datatype.lower().split("(", 1)[0].strip() not in SCALARS


def scalar_fields(node: etree._Element, allowed: set[str]) -> dict[str, str]:
    """Refuse unknown or duplicated native fields instead of losing them."""
    if node.attrib or (node.text or "").strip():
        raise ProjectError("Unsupported member metadata structure")
    fields: dict[str, str] = {}
    for child in node:
        key = str(child.tag)
        if (
            key not in allowed
            or key in fields
            or child.attrib
            or not is_text_node(child)
            or (child.tail or "").strip()
        ):
            raise ProjectError(f"Unsupported member metadata field: {key}")
        fields[key] = text_value(child)
    return fields


def read_tags(node: etree._Element) -> list[dict[str, str]]:
    if node.attrib or (node.text or "").strip():
        raise ProjectError("Unsupported member taggedvalues")
    result: list[dict[str, str]] = []
    marker = False
    for child in node:
        if (child.tail or "").strip():
            raise ProjectError("Unexpected member taggedvalues text")
        if child.tag == "row_class":
            if marker or child.attrib or len(child) or child.text != "taggedvalue":
                raise ProjectError("Unsupported member taggedvalues row_class")
            marker = True
        elif child.tag == "row":
            result.append(scalar_fields(child, {"name", "value"}))
        else:
            raise ProjectError("Unsupported member taggedvalues child")
    return result


def read_members(container: etree._Element, table: str) -> dict[str, Any]:
    from .parser import type_declaration

    if container.attrib or (container.text or "").strip():
        raise ProjectError(f"Unsupported {table} collection")
    result: dict[str, Any] = {}
    names: set[str] = set()
    marker = False
    for row in container:
        if (row.tail or "").strip():
            raise ProjectError(f"Unexpected text in {table}")
        if row.tag == "row_class":
            kind = "attributeobject" if table == "attributes" else "methodobject"
            if marker or row.attrib or len(row) or row.text != kind:
                raise ProjectError(f"Unsupported {table} row_class")
            marker = True
            continue
        if row.tag != "row" or row.attrib or (row.text or "").strip():
            raise ProjectError(f"Unsupported {table} row")
        allowed = COMMON | (
            {"defaultvalue", "defaultstring"} if table == "attributes" else set()
        )
        fields: dict[str, str] = {}
        tags: list[dict[str, str]] | None = None
        seen: set[str] = set()
        for child in row:
            key = str(child.tag)
            if key not in allowed or key in seen or (child.tail or "").strip():
                raise ProjectError(f"Unsupported member metadata field: {key}")
            seen.add(key)
            if key == "taggedvalues":
                tags = read_tags(child)
            else:
                if child.attrib or not is_text_node(child):
                    raise ProjectError(f"Unsupported member metadata field: {key}")
                fields[key] = text_value(child)
        name = fields.get("displayname")
        dtype = fields.get("datatype")
        if (
            not name
            or name.casefold() in names
            or (table == "attributes" and not dtype)
        ):
            raise ProjectError(f"Missing or duplicate {table} member identity/type")
        names.add(name.casefold())
        for flag in ("isarray", "isnullable", "isprivate"):
            if fields.get(flag, "0") not in {"0", "1", ""}:
                raise ProjectError(f"Unsupported member flag: {flag}")
        declaration = "PRIVATE " if fields.get("isprivate") == "1" else ""
        if table == "methods":
            declaration += "METHOD"
            if dtype:
                declaration += " RETURNING "
        if dtype:
            declaration += type_declaration(
                dtype, fields.get("isnullable") == "1", fields.get("isarray") == "1"
            )
        extra: dict[str, Any] = {}
        if table == "attributes":
            mode = fields.get("defaultvalue", "1")
            if mode == "2":
                declaration += " DEFAULT NULL"
            elif mode == "3":
                value = fields.get("defaultstring", "").replace("'", "''")
                declaration += f" DEFAULT '{value}'"
            elif mode not in {"", "0", "1"}:
                raise ProjectError(f"Unsupported member default mode: {mode}")
            # A saved string with DV_SYSTEM/DV_NULL is inactive; never promote it
            # to a DEFAULT literal. Retain it as metadata for native fidelity.
            if mode != "3" and "defaultstring" in fields:
                extra["defaultstring"] = fields["defaultstring"]
        elif not dtype:
            # Legacy metadata on a method with no return type cannot be expressed
            # as RETURNING without inventing a type. Keep it explicitly instead.
            for flag in ("isnullable", "isarray"):
                if fields.get(flag) == "1":
                    extra[flag] = True
        if "remark" in fields:
            extra["remark"] = fields["remark"]
        if tags:
            extra["taggedvalues"] = tags
        result[name] = {"declaration": declaration, **extra} if extra else declaration
    return result


def write_member(row: etree._Element, value: object, table: str) -> None:
    from .xml_shapes import order_children
    from .xml_writer import datatype

    extra: dict[str, Any] = {}
    if isinstance(value, dict):
        extra = dict(value)
        declaration = extra.pop("declaration", None)
    else:
        declaration = value
    allowed = {"remark", "taggedvalues"} | (
        {"defaultstring"} if table == "attributes" else {"isnullable", "isarray"}
    )
    if not isinstance(declaration, str) or extra.keys() - allowed:
        raise ProjectError("Invalid structured member declaration")
    # Build first so invalid input cannot partially destroy existing row metadata.
    replacement = etree.Element("row")
    name = row.find("displayname")
    if name is None:
        raise ProjectError("Member requires a displayname")
    set_text(etree.SubElement(replacement, "displayname"), text_value(name))
    decl = declaration
    if decl.startswith("PRIVATE "):
        etree.SubElement(replacement, "isprivate").text = "1"
        decl = decl[len("PRIVATE ") :]
    literal = False
    if table == "methods":
        match = re.fullmatch(r"METHOD(?: RETURNING (.+))?", decl, re.DOTALL)
        if not match:
            raise ProjectError(f"Invalid method declaration: {declaration}")
        decl = match[1] or ""
    else:
        match = re.fullmatch(
            r"(.+?) DEFAULT (NULL|'(?:[^']|'')*')", decl, re.DOTALL | re.IGNORECASE
        )
        if match:
            decl = match[1]
            literal = match[2].upper() != "NULL"
            etree.SubElement(replacement, "defaultvalue").text = "3" if literal else "2"
            if literal:
                set_text(
                    etree.SubElement(replacement, "defaultstring"),
                    match[2][1:-1].replace("''", "'"),
                    cdata=True,
                )
    if table == "attributes" and not decl:
        raise ProjectError("Attribute requires a type declaration")
    if decl:
        datatype(replacement, decl)
    if (
        replacement.findtext("defaultvalue") == "2"
        and replacement.findtext("isnullable") != "1"
    ):
        raise ProjectError("DEFAULT NULL requires a nullable attribute")
    for key in ("remark", "defaultstring"):
        if key in extra:
            if not isinstance(extra[key], str) or (key == "defaultstring" and literal):
                raise ProjectError(f"Invalid member {key}")
            set_text(etree.SubElement(replacement, key), extra[key], cdata=True)
    for key in ("isnullable", "isarray"):
        if key in extra:
            if decl or not isinstance(extra[key], bool):
                raise ProjectError(
                    f"{key} metadata requires a method without a return type"
                )
            if extra[key]:
                etree.SubElement(replacement, key).text = "1"
    if "taggedvalues" in extra:
        tags = extra["taggedvalues"]
        if not isinstance(tags, list):
            raise ProjectError("Member taggedvalues must be an array of tables")
        if tags:
            container = etree.SubElement(replacement, "taggedvalues")
            for item in tags:
                if (
                    not isinstance(item, dict)
                    or item.keys() - {"name", "value"}
                    or any(not isinstance(v, str) for v in item.values())
                ):
                    raise ProjectError("Invalid member tagged value")
                entry = etree.SubElement(container, "row")
                for key in ("name", "value"):
                    if key in item:
                        set_text(etree.SubElement(entry, key), item[key], cdata=True)
            etree.SubElement(container, "row_class").text = "taggedvalue"
    order_children(
        replacement, "attributeobject" if table == "attributes" else "methodobject"
    )
    row[:] = list(replacement)

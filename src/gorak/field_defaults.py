"""Parse and compare OpenROAD frame field defaults."""

from typing import Any

from lxml import etree

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
FieldDefaults = dict[str, dict[str, Any]]


def parse_field_defaults_node(node: etree._Element) -> FieldDefaults:
    """Parse an OpenROAD <fielddefaults> node into stable JSON-like data."""

    field_types: dict[str, Any] = {}
    for row in node.findall("row"):
        key = (row.findtext("clienttext") or "").strip()
        if not key:
            continue

        field_types[key] = parse_default_row(row)

    return {"field_types": field_types}


def parse_default_row(row: etree._Element) -> dict[str, Any]:
    childfields = row.find("childfields")
    properties = {
        child.tag: (child.text or "").strip()
        for child in row
        if child.tag not in {"clienttext", "childfields"}
    }

    parsed: dict[str, Any] = {
        "type": row.get(XSI_TYPE, ""),
        "properties": properties,
    }
    if childfields is not None:
        parsed["childfields"] = [
            parse_childfield_row(child) for child in childfields.findall("row")
        ]

    return parsed


def parse_childfield_row(row: etree._Element) -> dict[str, Any]:
    attributes = {key: value for key, value in row.attrib.items() if key != XSI_TYPE}
    properties = {child.tag: (child.text or "").strip() for child in row}
    return {
        "type": row.get(XSI_TYPE, ""),
        "attributes": attributes,
        "properties": properties,
    }

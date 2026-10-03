"""Parse and compare OpenROAD frame field defaults."""

from copy import deepcopy
from typing import Any

from lxml import etree

from .xml_text import find_text, is_text_node, text_value

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
FieldDefaults = dict[str, Any]
JsonObject = dict[str, Any]


def parse_field_defaults_node(node: etree._Element) -> FieldDefaults:
    """Parse an OpenROAD <fielddefaults> node into stable JSON-like data."""

    rows = node.findall("row")
    style_counts: dict[str, int] = {}
    field_styles: list[dict[str, Any]] = []
    common_container = common_matrix_container(rows)

    for row in rows:
        group = group_name(row, style_counts)
        childfields = row.find("childfields")
        if childfields is None:
            continue

        for child in childfields.findall("row"):
            field_type = child.get(XSI_TYPE, "")
            if not field_type:
                continue

            field_styles.append(parse_childfield_row(group, child))

    return {
        "common_model_container": common_container,
        "field_styles": field_styles,
    }


def common_matrix_container(rows: list[etree._Element]) -> dict[str, Any]:
    """Return matrixfield wrapper values shared by every default row."""

    containers = [matrix_container(row) for row in rows]
    properties = common_defaults(
        [container["properties"] for container in containers if container["properties"]]
    )
    if not containers:
        return {"type": "", "properties": {}}

    return {
        "type": containers[0]["type"],
        "properties": properties,
    }


def matrix_container(row: etree._Element) -> dict[str, Any]:
    properties = {
        child.tag: element_value(child)
        for child in row
        if child.tag not in {"clienttext", "childfields", "columns", "rows"}
    }
    return {
        "type": row.get(XSI_TYPE, ""),
        "properties": properties,
    }


def group_name(row: etree._Element, style_counts: dict[str, int]) -> str:
    base_name = (find_text(row, "clienttext") or "field").strip(" \t\r\n")
    style_counts[base_name] = style_counts.get(base_name, 0) + 1
    if style_counts[base_name] == 1:
        return base_name
    return f"{base_name}:{style_counts[base_name]}"


def parse_childfield_row(group: str, row: etree._Element) -> dict[str, Any]:
    properties = {child.tag: element_value(child) for child in row}
    return {
        "type": row.get(XSI_TYPE, ""),
        "group": group,
        "properties": properties,
    }


def element_value(node: etree._Element) -> Any:
    """Convert an XML property node into JSON-compatible data."""

    if is_text_node(node):
        return text_value(node).strip(" \t\r\n")

    value: dict[str, Any] = {}
    node_type = node.get(XSI_TYPE)
    attributes = {key: item for key, item in node.attrib.items() if key != XSI_TYPE}
    if node_type is not None:
        value["type"] = node_type
    if attributes:
        value["attributes"] = attributes

    for child in node:
        child_value = element_value(child)
        if child.tag == "row":
            value.setdefault("row", []).append(child_value)
        elif child.tag in value:
            existing = value[child.tag]
            if isinstance(existing, list):
                existing.append(child_value)
            else:
                value[child.tag] = [existing, child_value]
        else:
            value[child.tag] = child_value

    text = (node.text or "").strip(" \t\r\n")
    if text:
        value["text"] = text

    return value


def common_defaults(children: list[JsonObject]) -> JsonObject:
    """Return values that are present and equal in every child object."""

    if not children:
        return {}

    common: JsonObject = {}
    first = children[0]
    for key, first_value in first.items():
        values = [child[key] for child in children if key in child]
        if len(values) != len(children):
            continue
        if all(isinstance(value, dict) for value in values):
            nested = common_defaults(values)
            if nested:
                common[key] = nested
        elif all(value == first_value for value in values):
            common[key] = deepcopy(first_value)

    return common

"""Parse and compare OpenROAD frame field defaults."""

from copy import deepcopy
from typing import Any

from lxml import etree

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
FieldDefaults = dict[str, dict[str, Any]]
JsonObject = dict[str, Any]


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


def effective_defaults(
    repo_defaults: JsonObject,
    app_defaults: JsonObject,
    frame_defaults: JsonObject,
) -> JsonObject:
    """Merge repo, app, and frame defaults into one effective default set."""

    return merge_defaults(merge_defaults(repo_defaults, app_defaults), frame_defaults)


def merge_defaults(parent: JsonObject, override: JsonObject) -> JsonObject:
    """Recursively merge override values onto parent defaults."""

    merged = deepcopy(parent)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_defaults(merged[key], value)
        else:
            merged[key] = deepcopy(value)

    return merged


def diff_defaults(parent: JsonObject, child: JsonObject) -> JsonObject:
    """Return the smallest override object that turns parent into child."""

    diff: JsonObject = {}
    for key, child_value in child.items():
        if key not in parent:
            diff[key] = deepcopy(child_value)
            continue

        parent_value = parent[key]
        if isinstance(parent_value, dict) and isinstance(child_value, dict):
            nested_diff = diff_defaults(parent_value, child_value)
            if nested_diff:
                diff[key] = nested_diff
        elif parent_value != child_value:
            diff[key] = deepcopy(child_value)

    return diff

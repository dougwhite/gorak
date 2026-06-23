"""Parse and compare OpenROAD frame field defaults."""

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from lxml import etree

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
FieldDefaults = dict[str, Any]
JsonObject = dict[str, Any]


@dataclass(frozen=True)
class FlattenResult:
    promoted_values: int
    app_count: int


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
    base_name = (row.findtext("clienttext") or "field").strip()
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

    if len(node) == 0:
        return (node.text or "").strip()

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

    text = (node.text or "").strip()
    if text:
        value["text"] = text

    return value


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
        elif key == "field_styles" and isinstance(value, list):
            parent_value = merged.get(key)
            if isinstance(parent_value, list):
                merged[key] = merge_field_styles(parent_value, value)
            else:
                merged[key] = deepcopy(value)
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
        elif key == "field_styles" and isinstance(parent_value, list) and isinstance(
            child_value, list
        ):
            field_style_diff = diff_field_styles(parent_value, child_value)
            if field_style_diff:
                diff[key] = field_style_diff
        elif parent_value != child_value:
            diff[key] = deepcopy(child_value)

    return diff


def merge_field_styles(
    parent: list[Any],
    override: list[Any],
) -> list[Any]:
    """Merge ordered field-style property overrides onto parent styles."""

    if not all(is_field_style(style) for style in parent + override):
        return deepcopy(override)

    merged = deepcopy(parent)
    search_start = 0
    for override_style in override:
        match_index = next_field_style_index(merged, override_style, search_start)
        if match_index is None:
            merged.append(deepcopy(override_style))
            search_start = len(merged)
            continue

        parent_style = cast(JsonObject, merged[match_index])
        override_properties = cast(JsonObject, override_style).get("properties", {})
        if isinstance(override_properties, dict):
            parent_properties = parent_style.get("properties", {})
            if isinstance(parent_properties, dict):
                parent_style["properties"] = merge_defaults(
                    parent_properties,
                    override_properties,
                )
            else:
                parent_style["properties"] = deepcopy(override_properties)
        search_start = match_index + 1

    return merged


def diff_field_styles(parent: list[Any], child: list[Any]) -> list[Any]:
    """Return compact property diffs for aligned field-default style rows."""

    if len(parent) != len(child):
        return deepcopy(child)
    if not all(is_field_style(style) for style in parent + child):
        return deepcopy(child)

    style_diffs: list[Any] = []
    for parent_style, child_style in zip(parent, child, strict=True):
        parent_object = cast(JsonObject, parent_style)
        child_object = cast(JsonObject, child_style)
        if not same_field_style(parent_object, child_object):
            return deepcopy(child)

        parent_properties = cast(JsonObject, parent_object["properties"])
        child_properties = cast(JsonObject, child_object["properties"])
        property_diff = diff_defaults(parent_properties, child_properties)
        if property_diff:
            style_diffs.append(
                {
                    "type": child_object["type"],
                    "group": child_object["group"],
                    "properties": property_diff,
                }
            )

    return style_diffs


def next_field_style_index(
    styles: list[Any],
    target: Any,
    start: int,
) -> int | None:
    for index, style in enumerate(styles[start:], start=start):
        if same_field_style(cast(JsonObject, style), cast(JsonObject, target)):
            return index

    return None


def is_field_style(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("type"), str)
        and isinstance(value.get("group"), str)
        and isinstance(value.get("properties"), dict)
    )


def same_field_style(left: JsonObject, right: JsonObject) -> bool:
    return left.get("type") == right.get("type") and left.get("group") == right.get(
        "group"
    )


def flatten_app_defaults(root: Path) -> FlattenResult:
    """Promote identical app-level default overrides into repo defaults."""

    app_paths = app_field_default_paths(root)
    app_defaults = [read_defaults(path) for path in app_paths]
    shared_defaults = common_defaults(app_defaults)
    if not shared_defaults:
        return FlattenResult(promoted_values=0, app_count=len(app_paths))

    repo_path = root / "field_defaults.json"
    repo_defaults = read_defaults(repo_path)
    write_defaults(repo_path, merge_defaults(repo_defaults, shared_defaults))

    for path, defaults in zip(app_paths, app_defaults, strict=True):
        write_defaults(path, remove_defaults(defaults, shared_defaults))

    return FlattenResult(
        promoted_values=count_leaf_values(shared_defaults),
        app_count=len(app_paths),
    )


def app_field_default_paths(root: Path) -> list[Path]:
    return sorted(
        path / "field_defaults.json"
        for path in root.iterdir()
        if path.is_dir()
        and (path / "app.json").is_file()
        and (path / "field_defaults.json").is_file()
    )


def read_defaults(path: Path) -> JsonObject:
    if not path.is_file():
        return {}
    return cast(JsonObject, json.loads(path.read_text()))


def write_defaults(path: Path, defaults: JsonObject) -> None:
    path.write_text(json.dumps(defaults, indent=4) + "\n")


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


def remove_defaults(child: JsonObject, defaults: JsonObject) -> JsonObject:
    """Remove matching default values from a child override object."""

    result = deepcopy(child)
    for key, default_value in defaults.items():
        if key not in result:
            continue
        child_value = result[key]
        if isinstance(child_value, dict) and isinstance(default_value, dict):
            nested = remove_defaults(child_value, default_value)
            if nested:
                result[key] = nested
            else:
                del result[key]
        elif child_value == default_value:
            del result[key]

    return result


def count_leaf_values(defaults: JsonObject) -> int:
    count = 0
    for value in defaults.values():
        if isinstance(value, dict):
            count += count_leaf_values(value)
        elif isinstance(value, list):
            count += sum(
                count_leaf_values(item) if isinstance(item, dict) else 1
                for item in value
            )
        else:
            count += 1
    return count

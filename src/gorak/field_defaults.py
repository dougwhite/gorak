"""Parse and compare OpenROAD frame field defaults."""

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from lxml import etree

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
FieldDefaults = dict[str, dict[str, Any]]
JsonObject = dict[str, Any]


@dataclass(frozen=True)
class FlattenResult:
    promoted_values: int
    app_count: int


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
        else:
            count += 1
    return count

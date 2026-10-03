"""Native stylesheet inheritance by group name and fixed, numbered style slots."""

import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any, TypeGuard
from urllib.parse import quote

from lxml import etree

from .errors import ProjectError
from .style_values import XSI, decode_value, encode_value, numbered
from .style_values import difference as property_difference
from .style_values import merge as merge_properties

Json = dict[str, Any]


def group_key(name: str, occurrence: int) -> str:
    # Literal colon/percent characters must not collide with repeated-group labels.
    label = quote(name, safe=" _-.")
    return label if occurrence == 1 else f"{label}:{occurrence}"


def without_rows(node: etree._Element) -> etree._Element:
    result = deepcopy(node)
    rows = result.findall("row")
    if list(result)[: len(rows)] != rows:
        raise ProjectError(
            "Stylesheet arrays require native rows before container metadata"
        )
    for row in rows:
        result.remove(row)
    if not (result.text or "").strip():
        result.text = None
    return result


def encode(node: etree._Element) -> Json:
    """Preserve group metadata and samples without suppressing native properties."""
    if node.tag != "fielddefaults":
        raise ProjectError("Native stylesheet root must be fielddefaults")
    groups: Json = {}
    counts: dict[str, int] = {}
    for row in node.findall("row"):
        name = row.findtext("clienttext", "")
        counts[name] = counts.get(name, 0) + 1
        key = group_key(name, counts[name])
        wrapper = deepcopy(row)
        children = row.find("childfields")
        styles: Json = {}
        if children is not None:
            wrapper.replace(wrapper.find("childfields"), without_rows(children))
            styles = {
                f"style{i}": encode_value(style)
                for i, style in enumerate(children.findall("row"), 1)
            }
        groups[key] = {
            "properties": encode_value(wrapper, object_value=True),
            "styles": styles,
        }
    return {
        "properties": encode_value(without_rows(node), object_value=True),
        "group_order": list(groups),
        "groups": groups,
    }


def decode(value: Json) -> etree._Element:
    if not isinstance(value, dict) or set(value) != {
        "properties",
        "group_order",
        "groups",
    }:
        raise ProjectError(
            "Invalid native stylesheet: expected properties, group_order and groups"
        )
    order, groups = value["group_order"], value["groups"]
    if (
        not isinstance(groups, dict)
        or not isinstance(order, list)
        or any(not isinstance(k, str) for k in order)
        or len(order) != len(set(order))
        or set(order) != set(groups)
    ):
        raise ProjectError("Group order must name each native group exactly once")
    result = decode_value("fielddefaults", value["properties"])
    if result.findall("row"):
        raise ProjectError("Native groups belong in groups, not root properties")
    counts: dict[str, int] = {}
    for index, key in enumerate(order):
        group = groups[key]
        if not isinstance(group, dict) or set(group) != {"properties", "styles"}:
            raise ProjectError(f"Invalid native stylesheet group: {key}")
        row = decode_value("row", group["properties"])
        name = row.findtext("clienttext", "")
        counts[name] = counts.get(name, 0) + 1
        if group_key(name, counts[name]) != key:
            raise ProjectError(
                f"Group label does not match its native name/occurrence: {key}"
            )
        styles = group["styles"]
        slots = numbered(styles, "style")
        children = row.find("childfields")
        if children is not None and children.findall("row"):
            raise ProjectError(
                "Native style entries belong in styles, not group properties"
            )
        if slots and children is None:
            raise ProjectError(f"Missing native childfields container for {key}")
        for position, slot in enumerate(slots):
            field = decode_value("row", styles[slot])
            if not field.get(XSI):
                raise ProjectError(f"Native field type required for {key}/{slot}")
            assert children is not None
            children.insert(position, field)
        result.insert(index, row)
    return result


def validate(stylesheet: Json) -> None:
    decode(stylesheet)


def complete(stylesheet: Json) -> Json:
    """A standalone root contains its complete named stylesheet, without a parent."""
    validate(stylesheet)
    return {"standalone": True, **deepcopy(stylesheet)}


def empty_delta() -> Json:
    """No properties supplied means inherit the parent unchanged."""
    return {}


def has_overrides(layer: Json) -> bool:
    return bool(layer)


def difference(parent: Json, desired: Json) -> Json:
    validate(parent)
    validate(desired)
    return property_difference(parent, desired)


def is_native_layer(value: Any) -> TypeGuard[Json]:
    """Recognise named stylesheet properties without a source version marker."""
    return isinstance(value, dict) and not set(value) - {
        "standalone",
        "properties",
        "group_order",
        "groups",
        "$order",
        "$before",
    }


def resolve(parent: Json | None, layer: Json) -> Json:
    if not is_native_layer(layer):
        raise ProjectError(
            "Unsupported stylesheet properties; re-export the application"
        )
    values = {key: value for key, value in layer.items() if key != "standalone"}
    if "standalone" in layer:
        if layer["standalone"] is not True:
            raise ProjectError("standalone must be true or omitted")
        result = deepcopy(values)
    else:
        if parent is None:
            raise ProjectError("An inherited stylesheet requires its parent")
        validate(parent)
        result = merge_properties(parent, values)
    validate(result)
    return result


def baseline() -> Json:
    data = json.loads(
        files("gorak.templates").joinpath("native_styles.json").read_text()
    )
    return resolve(None, data)


def read(path: Path) -> Json:
    if not path.exists():
        return empty_delta()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as ex:
        raise ProjectError(f"Cannot read stylesheet: {path}") from ex
    if not is_native_layer(value):
        raise ProjectError(
            "Unsupported stylesheet properties; re-export the application"
        )
    return value


def project_styles(root: Path) -> Json:
    layer = read(root / "field_defaults.json")
    return resolve(None if layer.get("standalone") is True else baseline(), layer)


def parent_styles(folder: Path) -> Json:
    return resolve(project_styles(folder.parent), read(folder / "field_defaults.json"))


def frame_styles(source: Path) -> Json:
    return resolve(
        parent_styles(source.parent), read(source.with_suffix(".fielddefaults.json"))
    )


def entries(stylesheet: Json) -> list[Json]:
    node = decode(stylesheet)
    counts: dict[str, int] = {}
    result = []
    for group in node.findall("row"):
        name = group.findtext("clienttext", "")
        counts[name] = counts.get(name, 0) + 1
        for ordinal, style in enumerate(group.findall("childfields/row"), 1):
            result.append(
                {
                    "group": name,
                    "group_ordinal": counts[name],
                    "style_ordinal": ordinal,
                    "type": style.get(XSI, ""),
                    "sample": encode_value(style),
                }
            )
    return result

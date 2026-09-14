"""Lossless palettes with repository/application/frame property inheritance."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from lxml import etree

from .errors import ProjectError
from .field_defaults import common_defaults, group_name, read_defaults
from .readable_values import XSI, decode_value, encode_properties, encode_value
from .xml_shapes import order_children

Json = dict[str, Any]
DELETE = {"_delete": True}


def identities(styles: list[Any]) -> list[tuple[str, str, int]]:
    counts: dict[tuple[str, str], int] = {}
    result = []
    for style in styles:
        if (
            not isinstance(style, dict)
            or not isinstance(style.get("group"), str)
            or not isinstance(style.get("type"), str)
        ):
            raise ProjectError("Invalid field-style identity")
        key = (style["group"], style["type"])
        counts[key] = counts.get(key, 0) + 1
        result.append((*key, counts[key]))
    return result


def merge(parent: Json, override: Json) -> Json:
    result = deepcopy(parent)
    for key, value in override.items():
        if value == DELETE:
            result.pop(key, None)
        elif isinstance(value, dict) and set(value) == {"_replace"}:
            result[key] = deepcopy(value["_replace"])
        elif key == "field_styles" and isinstance(value, dict) and "_order" in value:
            existing = result.get(key, [])
            by_id = dict(zip(identities(existing), deepcopy(existing), strict=True))
            for style in value.get("_changes", []):
                identity = (style["group"], style["type"], style.get("occurrence", 1))
                delta = {k: v for k, v in style.items() if k != "occurrence"}
                by_id[identity] = merge(by_id.get(identity, {}), delta)
            try:
                result[key] = [by_id[tuple(identity)] for identity in value["_order"]]
            except (KeyError, TypeError) as ex:
                raise ProjectError("Invalid field-style order override") from ex
        elif key == "field_styles" and isinstance(value, list):
            rows = deepcopy(result.get(key, []))
            keys = identities(rows)
            seen: dict[tuple[str, str], int] = {}
            for style in value:
                pair = (style["group"], style["type"])
                occurrence = style.get("occurrence", seen.get(pair, 0) + 1)
                seen[pair] = occurrence
                identity = (*pair, occurrence)
                delta = {k: v for k, v in style.items() if k != "occurrence"}
                if identity in keys:
                    index = keys.index(identity)
                    rows[index] = merge(rows[index], delta)
                else:
                    rows.append(deepcopy(delta))
                    keys = identities(rows)
            result[key] = rows
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def difference(parent: Json, child: Json) -> Json:
    result: Json = {key: DELETE.copy() for key in parent.keys() - child.keys()}
    for key, value in child.items():
        if key not in parent:
            result[key] = deepcopy(value)
        elif (
            key == "field_styles"
            and isinstance(value, list)
            and isinstance(parent[key], list)
        ):
            before = parent[key]
            if identities(before) != identities(value):
                existing = dict(zip(identities(before), before, strict=True))
                changes = []
                for identity, row in zip(identities(value), value, strict=True):
                    delta = difference(existing.get(identity, {}), row)
                    if delta:
                        changes.append(
                            {
                                "group": identity[0],
                                "type": identity[1],
                                "occurrence": identity[2],
                                **delta,
                            }
                        )
                result[key] = {
                    "_order": [list(i) for i in identities(value)],
                    "_changes": changes,
                }
                continue
            rows = []
            for identity, old, new in zip(
                identities(value), before, value, strict=True
            ):
                delta = difference(old, new)
                if delta:
                    row = {"group": identity[0], "type": identity[1], **delta}
                    if identity[2] > 1:
                        row["occurrence"] = identity[2]
                    rows.append(row)
            if rows:
                result[key] = rows
        elif isinstance(value, dict) and isinstance(parent[key], dict):
            delta = difference(parent[key], value)
            if delta:
                result[key] = delta
        elif value != parent[key]:
            result[key] = deepcopy(value)
    return result


def legacy_keys(value: Any, *, decode: bool = False) -> Any:
    """Retain the established nested palette property spelling."""
    names = {"_type": "type", "_attributes": "attributes", "_text": "text"}
    if decode:
        names = {v: k for k, v in names.items()}
    if isinstance(value, list):
        return [legacy_keys(v, decode=decode) for v in value]
    if isinstance(value, dict):
        return {
            names.get(k, k): legacy_keys(v, decode=decode) for k, v in value.items()
        }
    return value


def encode(node: etree._Element) -> Json:
    rows = node.findall("row")
    wrappers = [
        encode_properties(
            r,
            r.get(XSI, "matrixfield"),
            {"clienttext", "childfields", "columns", "rows"},
        )
        for r in rows
    ]
    common = common_defaults(wrappers)
    common_type = rows[0].get(XSI, "matrixfield") if rows else "matrixfield"
    styles = []
    groups: Json = {}
    counts: dict[str, int] = {}
    for row in rows:
        group = group_name(row, counts)
        kind = row.get(XSI, "matrixfield")
        properties = encode_properties(row, kind, {"childfields"})
        wrapper: Json = {"properties": difference(common, properties)}
        if kind != common_type:
            wrapper["type"] = kind
        wrapper["typed"] = XSI in row.attrib
        attributes = {k: v for k, v in row.attrib.items() if k != XSI}
        if attributes:
            wrapper["attributes"] = attributes
        children = row.find("childfields")
        if children is not None:
            container = deepcopy(children)
            for child in container.findall("row"):
                container.remove(child)
            if not (container.text or "").strip():
                container.text = None
            wrapper["childfields"] = legacy_keys(
                encode_value(container, "formfield_ARRAY")
            )
            for child in children.findall("row"):
                field_type = child.get(XSI)
                if not field_type:
                    raise ProjectError("Palette style requires an explicit type")
                style: Json = {
                    "type": field_type,
                    "group": group,
                    "properties": {
                        k: legacy_keys(v)
                        for k, v in encode_properties(child, field_type, set()).items()
                    },
                }
                attributes = {k: v for k, v in child.attrib.items() if k != XSI}
                if attributes:
                    style["attributes"] = attributes
                styles.append(style)
        groups[group] = wrapper
    container = deepcopy(node)
    for row in container.findall("row"):
        container.remove(row)
    if not (container.text or "").strip():
        container.text = None
    return {
        "common_model_container": {
            "type": common_type,
            "properties": {k: legacy_keys(v) for k, v in common.items()},
        },
        "field_styles": styles,
        "structure": {
            "container": legacy_keys(encode_value(container, "formfield_ARRAY")),
            "group_order": list(groups),
            "groups": groups,
        },
    }


def decode(values: Json) -> etree._Element:
    try:
        structure = values["structure"]
        common = values["common_model_container"]
        if set(values) - {"structure", "common_model_container", "field_styles"} or set(
            structure
        ) - {"container", "group_order", "groups"}:
            raise ProjectError("Unsupported inherited palette metadata")
        order = structure["group_order"]
        if len(order) != len(set(order)) or set(order) != set(structure["groups"]):
            raise ProjectError("Palette group order must name each group exactly once")
        for style in values["field_styles"]:
            if set(style) - {"group", "type", "properties", "attributes"}:
                raise ProjectError("Unsupported field-style metadata")
            if (
                style["group"] not in order
                or "childfields" not in structure["groups"][style["group"]]
            ):
                raise ProjectError("Field style has no palette group container")
        result = decode_value(
            "fielddefaults",
            legacy_keys(structure["container"], decode=True),
            "formfield_ARRAY",
        )
        for group in structure["group_order"]:
            wrapper = structure["groups"][group]
            if set(wrapper) - {
                "properties",
                "type",
                "typed",
                "attributes",
                "childfields",
            }:
                raise ProjectError("Unsupported palette group metadata")
            kind = wrapper.get("type", common["type"])
            props = merge(
                {
                    k: legacy_keys(v, decode=True)
                    for k, v in common["properties"].items()
                },
                wrapper["properties"],
            )
            row = decode_value("row", props, kind)
            if wrapper.get("typed", True):
                row.set(XSI, kind)
            row.attrib.update(wrapper.get("attributes", {}))
            if "childfields" in wrapper:
                children = decode_value(
                    "childfields",
                    legacy_keys(wrapper["childfields"], decode=True),
                    "formfield_ARRAY",
                )
                for style in values["field_styles"]:
                    if style["group"] != group:
                        continue
                    field = decode_value(
                        "row",
                        {
                            k: legacy_keys(v, decode=True)
                            for k, v in style["properties"].items()
                        },
                        style["type"],
                    )
                    field.set(XSI, style["type"])
                    field.attrib.update(style.get("attributes", {}))
                    children.append(field)
                order_children(children, "formfield_ARRAY")
                row.append(children)
            order_children(row, kind)
            result.append(row)
        order_children(result, "formfield_ARRAY")
        return result
    except (KeyError, TypeError, AttributeError) as ex:
        raise ProjectError("Incomplete or invalid inherited field defaults") from ex


def parent_defaults(folder: Path) -> Json:
    return merge(
        read_defaults(folder.parent / "field_defaults.json"),
        read_defaults(folder / "field_defaults.json"),
    )


def upgrade_legacy(repo: Json, desired: Json, *, metadata: bool = True) -> Json:
    """Add metadata the old projection omitted without replacing user values."""

    def whitespace(old: Any, native: Any) -> Any:
        if isinstance(old, str) and isinstance(native, str) and old == native.strip():
            return native
        if isinstance(old, dict) and isinstance(native, dict):
            return {
                k: whitespace(v, native[k]) if k in native else deepcopy(v)
                for k, v in old.items()
            }
        if (
            isinstance(old, list)
            and isinstance(native, list)
            and len(old) == len(native)
        ):
            return [whitespace(a, b) for a, b in zip(old, native, strict=True)]
        return deepcopy(old)

    result = deepcopy(repo)
    desired_styles = dict(
        zip(identities(desired["field_styles"]), desired["field_styles"], strict=True)
    )
    for key, style in zip(
        identities(result.get("field_styles", [])),
        result.get("field_styles", []),
        strict=True,
    ):
        native = desired_styles.get(key)
        if native is None:
            continue
        style["properties"] = whitespace(style["properties"], native["properties"])
        if metadata and "attributes" in native and "attributes" not in style:
            style["attributes"] = deepcopy(native["attributes"])
    if metadata:
        result["structure"] = deepcopy(desired["structure"])
    return result


def prepare(root: Path, folder: Path, nodes: list[etree._Element]) -> Json:
    """Seed missing layers; never replace existing authoritative property values."""
    from .project import write_json

    first = next(
        (n.find("fielddefaults") for n in nodes if n.find("fielddefaults") is not None),
        None,
    )
    if first is None:
        return parent_defaults(folder)
    desired = encode(first)
    repo_path = root / "field_defaults.json"
    repo = read_defaults(repo_path)
    if not repo_path.exists():
        repo = desired
        write_json(repo_path, repo)
    elif "structure" not in repo:
        repo = upgrade_legacy(repo, desired)
        write_json(repo_path, repo)
    app_path = folder / "field_defaults.json"
    if not app_path.exists():
        write_json(app_path, difference(repo, desired))
    return parent_defaults(folder)

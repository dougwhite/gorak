"""Exact native stylesheet values, independent of live field properties.

Ordered children retain repeated groups and styles, including identical entries.
Structural edits replace the ordered child list; they never search for a similar
style or append an unmatched override. Scalar changes use explicit tree paths.
"""

import hashlib
import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from lxml import etree

from .errors import ProjectError
from .xml_text import is_text_node, set_text, text_value

SCHEMA = "gorak-native-styles-v1"
Json = dict[str, Any]


def encode(node: etree._Element) -> Json:
    """Preserve native attributes, order, scripts and inline resource payloads."""
    if not isinstance(node.tag, str):
        raise ProjectError("Stylesheet requires an XML element")
    result: Json = {"tag": node.tag}
    if node.attrib:
        result["attributes"] = dict(node.attrib)
    if is_text_node(node):
        result["text"] = text_value(node)
    else:
        if (node.text or "").strip() or any((c.tail or "").strip() for c in node):
            raise ProjectError("Mixed stylesheet content is unsupported")
        result["children"] = [encode(child) for child in node]
    return result


def decode(value: Json) -> etree._Element:
    """Decode only the defined representation; reject malformed source."""
    if not isinstance(value, dict) or set(value) - {
        "tag",
        "attributes",
        "text",
        "children",
    }:
        raise ProjectError("Invalid native stylesheet node")
    tag = value.get("tag")
    attributes = value.get("attributes", {})
    if (
        not isinstance(tag, str)
        or not isinstance(attributes, dict)
        or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in attributes.items()
        )
    ):
        raise ProjectError("Invalid native stylesheet tag or attributes")
    try:
        node = etree.Element(tag, attrib=attributes)
    except (ValueError, TypeError) as ex:
        raise ProjectError("Invalid native stylesheet XML name") from ex
    if ("text" in value) == ("children" in value):
        raise ProjectError("Stylesheet node requires text or children")
    if "text" in value:
        if not isinstance(value["text"], str):
            raise ProjectError("Stylesheet text must be a string")
        set_text(node, value["text"])
    else:
        children = value["children"]
        if not isinstance(children, list):
            raise ProjectError("Stylesheet children must be an ordered list")
        node.extend(decode(child) for child in children)
    return node


def complete(stylesheet: Json) -> Json:
    """A complete layer never consults a parent or built-in baseline."""
    validate(stylesheet)
    return {"schema": SCHEMA, "mode": "complete", "stylesheet": deepcopy(stylesheet)}


def validate(stylesheet: Json) -> None:
    if decode(stylesheet).tag != "fielddefaults":
        raise ProjectError("Native stylesheet root must be fielddefaults")


def difference(parent: Json, desired: Json) -> Json:
    """Produce deterministic replacement operations at explicit native paths.

    A child-list replacement defines add/remove/reorder semantics atomically,
    preserving duplicates and resetting omitted properties to absence.
    """
    validate(parent)
    validate(desired)
    changes: list[Json] = []

    def visit(before: Any, after: Any, path: list[str | int]) -> None:
        if before == after:
            return
        if (
            isinstance(before, dict)
            and isinstance(after, dict)
            and before.keys() == after.keys()
        ):
            for key in sorted(after):
                visit(before[key], after[key], [*path, key])
        elif (
            isinstance(before, list)
            and isinstance(after, list)
            and len(before) == len(after)
        ):
            for i, (old, new) in enumerate(zip(before, after, strict=True)):
                visit(old, new, [*path, i])
        else:
            changes.append({"path": path, "value": deepcopy(after)})

    visit(parent, desired, [])
    return {
        "schema": SCHEMA,
        "mode": "delta",
        "parent_structure": structure_id(parent),
        "changes": changes,
    }


def resolve(parent: Json | None, layer: Json) -> Json:
    """Resolve a complete or parent-relative stylesheet, with no style matching."""
    if not isinstance(layer, dict) or layer.get("schema") != SCHEMA:
        raise ProjectError("Legacy defaults require authoritative native re-export")
    if layer.get("mode") == "complete" and set(layer) == {
        "schema",
        "mode",
        "stylesheet",
    }:
        result = deepcopy(layer["stylesheet"])
    elif layer.get("mode") == "delta" and set(layer) in (
        {"schema", "mode", "changes"},
        {"schema", "mode", "changes", "parent_structure"},
    ):
        if parent is None:
            raise ProjectError("A delta stylesheet requires its parent")
        validate(parent)
        if layer.get("changes") and layer.get("parent_structure") != structure_id(
            parent
        ):
            raise ProjectError(
                "Stylesheet parent structure changed; rebase from authoritative source"
            )
        result = deepcopy(parent)
        changes = layer["changes"]
        if not isinstance(changes, list):
            raise ProjectError("Stylesheet changes must be a list")
        seen: list[list[str | int]] = []
        for change in changes:
            if not isinstance(change, dict) or set(change) != {"path", "value"}:
                raise ProjectError("Invalid stylesheet change")
            path = change["path"]
            if not isinstance(path, list) or any(
                not isinstance(p, (str, int)) or isinstance(p, bool) for p in path
            ):
                raise ProjectError("Invalid stylesheet path")
            if any(path[: len(p)] == p or p[: len(path)] == path for p in seen):
                raise ProjectError("Overlapping stylesheet changes")
            seen.append(path)
            if not path:
                result = deepcopy(change["value"])
                continue
            target: Any = result
            for key in path[:-1]:
                target = lookup(target, key)
            lookup(target, path[-1])
            target[path[-1]] = deepcopy(change["value"])
    else:
        raise ProjectError("Invalid stylesheet layer mode or keys")
    validate(result)
    return cast(Json, result)


def lookup(target: Any, key: str | int) -> Any:
    if isinstance(target, dict) and isinstance(key, str) and key in target:
        return target[key]
    if isinstance(target, list) and isinstance(key, int) and 0 <= key < len(target):
        return target[key]
    raise ProjectError("Stylesheet path does not exist in parent")


def baseline() -> Json:
    data = json.loads(
        files("gorak.templates").joinpath("native_styles.json").read_text()
    )
    return resolve(None, data)


def empty_delta() -> Json:
    return {"schema": SCHEMA, "mode": "delta", "changes": []}


def read(path: Path) -> Json:
    if not path.exists():
        return empty_delta()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as ex:
        raise ProjectError(f"Cannot read stylesheet: {path}") from ex
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ProjectError(
            "Legacy defaults require authoritative native re-export or gorak styles migrate"
        )
    return value


def project_styles(root: Path) -> Json:
    layer = read(root / "field_defaults.json")
    return resolve(None if layer.get("mode") == "complete" else baseline(), layer)


def parent_styles(folder: Path) -> Json:
    return resolve(project_styles(folder.parent), read(folder / "field_defaults.json"))


def frame_styles(source: Path) -> Json:
    return resolve(
        parent_styles(source.parent), read(source.with_suffix(".fielddefaults.json"))
    )


def is_native_source(path: Path) -> bool:
    import tomllib

    from .parser import split_w4gl

    return tomllib.loads(split_w4gl(path.read_text())[0]).get("source_format") == 3


def structure_id(value: Json) -> str:
    def shape(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: item[key]
                if key in {"tag", "{http://www.w3.org/2001/XMLSchema-instance}type"}
                or (key == "text" and item.get("tag") == "clienttext")
                else shape(item[key])
                for key in sorted(item)
            }
        if isinstance(item, list):
            return [shape(child) for child in item]
        return type(item).__name__

    return hashlib.sha256(json.dumps(shape(value), sort_keys=True).encode()).hexdigest()


def entries(stylesheet: Json) -> list[Json]:
    """Native identities and complete creation samples for designer consumers."""
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
                    "type": style.get(
                        "{http://www.w3.org/2001/XMLSchema-instance}type", ""
                    ),
                    "sample": encode(style),
                }
            )
    return result

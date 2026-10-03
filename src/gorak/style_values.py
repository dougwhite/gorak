"""Named, lossless XML properties used inside native stylesheet entries."""

from copy import deepcopy
from typing import Any

from lxml import etree

from .errors import ProjectError
from .xml_text import is_text_node, set_text, text_value

XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"
Json = dict[str, Any]


def numbered(values: Any, prefix: str) -> list[str]:
    """Numeric slot names are authoritative, regardless of JSON key order."""
    if not isinstance(values, dict):
        raise ProjectError(f"Expected named {prefix} entries")
    expected = [f"{prefix}{i}" for i in range(1, len(values) + 1)]
    if set(values) != set(expected):
        raise ProjectError(
            f"{prefix} numbers must be contiguous from {prefix}1; entries are never renumbered implicitly"
        )
    return expected


def encode_value(node: etree._Element, *, object_value: bool = False) -> Any:
    if not isinstance(node.tag, str):
        raise ProjectError("Stylesheet requires an XML element")
    if is_text_node(node) and not node.attrib and not object_value:
        return text_value(node)
    value: Json = {}
    if XSI in node.attrib:
        value["_type"] = node.get(XSI)
    attributes = {key: item for key, item in node.attrib.items() if key != XSI}
    if attributes:
        value["_attributes"] = attributes
    if is_text_node(node):
        text = text_value(node)
        if text or not object_value:
            value["_text"] = text
        return value
    if (node.text or "").strip() or any((child.tail or "").strip() for child in node):
        raise ProjectError("Mixed stylesheet content is unsupported")
    previous = None
    for child in node:
        key = child.tag
        if not isinstance(key, str) or key.startswith(("_", "$")):
            raise ProjectError("Unsupported stylesheet property name")
        if key == "row":
            if key in value and previous != key:
                raise ProjectError("Interleaved stylesheet rows are unsupported")
            rows = value.setdefault(key, {})
            rows[f"row{len(rows) + 1}"] = encode_value(child)
        elif key in value:
            raise ProjectError(f"Duplicate stylesheet property: {key}")
        else:
            value[key] = encode_value(child)
        previous = key
    return value


def decode_value(tag: str, value: Any) -> etree._Element:
    try:
        node = etree.Element(tag)
        if isinstance(value, str):
            set_text(node, value)
            return node
        if not isinstance(value, dict):
            raise ProjectError(f"Stylesheet property must be text or an object: {tag}")
        if "_type" in value:
            if not isinstance(value["_type"], str):
                raise ProjectError("Invalid native stylesheet type")
            node.set(XSI, value["_type"])
        attributes = value.get("_attributes", {})
        if not isinstance(attributes, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or k == XSI
            for k, v in attributes.items()
        ):
            raise ProjectError("Invalid native stylesheet attributes")
        node.attrib.update(attributes)
        if "_text" in value:
            if set(value) - {"_type", "_attributes", "_text"} or not isinstance(
                value["_text"], str
            ):
                raise ProjectError("Stylesheet text cannot contain nested properties")
            set_text(node, value["_text"])
        for key, item in value.items():
            if key in {"_type", "_attributes", "_text"}:
                continue
            if not isinstance(key, str) or key.startswith(("_", "$")):
                raise ProjectError("Unsupported stylesheet property name")
            if key == "row":
                node.extend(
                    decode_value("row", item[name]) for name in numbered(item, "row")
                )
            else:
                node.append(decode_value(key, item))
        return node
    except (TypeError, ValueError) as ex:
        raise ProjectError(f"Invalid native stylesheet property: {tag}") from ex


def difference(parent: Json, desired: Json) -> Json:
    """Ordinary named property overrides; null removes an inherited property."""
    result: Json = {}
    for key, value in desired.items():
        if key not in parent:
            result[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(parent[key], dict):
            child = difference(parent[key], value)
            if child:
                result[key] = child
        elif value != parent[key]:
            result[key] = deepcopy(value)
    for key in parent:
        if key not in desired:
            result[key] = None
    inherited_order = [key for key in parent if key in desired]
    inherited_order.extend(key for key in desired if key not in parent)
    desired_order = list(desired)
    before = {}
    for index in range(len(desired_order) - 2, -1, -1):
        key, following = desired_order[index : index + 2]
        if key not in parent and inherited_order.index(
            key
        ) + 1 != inherited_order.index(following):
            before[key] = following
            inherited_order.remove(key)
            inherited_order.insert(inherited_order.index(following), key)
    if inherited_order != desired_order:
        result["$order"] = desired_order
    elif before:
        result["$before"] = before
    return result


def merge(parent: Json, overrides: Json) -> Json:
    result = deepcopy(parent)
    for key, value in overrides.items():
        if key in {"$order", "$before"}:
            continue
        if value is None:
            if key not in result:
                raise ProjectError(f"Cannot remove absent stylesheet property: {key}")
            del result[key]
        elif isinstance(value, dict):
            previous = result.get(key, {})
            if not isinstance(previous, dict):
                previous = {}
            result[key] = merge(previous, value)
        else:
            result[key] = deepcopy(value)
    if "$before" in overrides:
        before = overrides["$before"]
        if not isinstance(before, dict) or any(
            not isinstance(key, str)
            or not isinstance(target, str)
            or key not in result
            or target not in result
            or key == target
            for key, target in before.items()
        ):
            raise ProjectError(
                "Property insertion hints must name existing distinct properties"
            )
        order = list(result)
        pending = dict(before)
        while pending:
            ready = [key for key, target in pending.items() if target not in pending]
            if not ready:
                raise ProjectError("Cyclic stylesheet property insertion hints")
            for key in ready:
                target = pending.pop(key)
                order.remove(key)
                order.insert(order.index(target), key)
        result = {key: result[key] for key in order}
    if "$order" in overrides:
        order = overrides["$order"]
        if (
            not isinstance(order, list)
            or any(not isinstance(k, str) for k in order)
            or len(order) != len(set(order))
            or set(order) != set(result)
        ):
            raise ProjectError(
                "Property order must name every remaining property exactly once"
            )
        result = {key: result[key] for key in order}
    return result

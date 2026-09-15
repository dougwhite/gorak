"""Lossless named metadata values; no scripts or full-component shadow copies."""

from typing import Any

from lxml import etree

from .errors import ProjectError
from .xml_shapes import derives, node_kind, order_children, shape, shapes


def properties(kind: str) -> dict[str, str]:
    if kind.startswith("xs:"):
        return {}
    return shape(kind)


def validate_type(kind: str, base: str) -> None:
    if not derives(kind, base):
        raise ProjectError(f"Source type {kind} does not derive from {base}")


XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"


def encode_value(node: etree._Element, kind: str) -> Any:
    actual = node_kind(node, kind)
    validate_type(actual, kind)
    kind = actual
    attributes = {k: v for k, v in node.attrib.items() if k != XSI}
    if not len(node) and not node.attrib:
        return node.text or ""
    value: dict[str, Any] = {}
    if XSI in node.attrib:
        value["_type"] = kind
    if attributes:
        value["_attributes"] = attributes
    if node.text is not None and (not len(node) or node.text.strip()):
        value["_text"] = node.text
    fields = properties(kind)
    for child in node:
        if child.tag not in fields or (child.tail or "").strip():
            raise ProjectError(f"Unsupported source structure: {kind}/{child.tag}")
        key = str(child.tag)
        item = encode_value(child, fields[key])
        if key == "row":
            value.setdefault(key, []).append(item)
        elif key in value:
            raise ProjectError(f"Duplicate source property: {kind}/{key}")
        else:
            value[key] = item
    return value


def decode_value(tag: str, value: Any, kind: str) -> etree._Element:
    node = etree.Element(tag)
    if isinstance(value, (str, int, bool)):
        if kind in shapes() and value != "":
            raise ProjectError(f"Structured source property requires a table: {tag}")
        node.text = str(int(value)) if isinstance(value, bool) else str(value)
        return node
    if not isinstance(value, dict):
        raise ProjectError(f"Invalid source property: {tag}")
    if "_type" in value:
        if not isinstance(value["_type"], str):
            raise ProjectError(f"Invalid source type: {tag}")
        validate_type(value["_type"], kind)
        kind = value["_type"]
        node.set(XSI, kind)
    attributes = value.get("_attributes", {})
    if not isinstance(attributes, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) or k == XSI
        for k, v in attributes.items()
    ):
        raise ProjectError(f"Invalid source attributes: {tag}")
    node.attrib.update(attributes)
    fields = properties(kind)
    for key, item in value.items():
        if key in {"_type", "_attributes"}:
            continue
        if key == "_text":
            if not isinstance(item, str):
                raise ProjectError(f"Invalid source text: {tag}")
            node.text = item
            continue
        if key not in fields:
            raise ProjectError(f"Unsupported source property: {kind}/{key}")
        if key == "row":
            if not isinstance(item, list):
                raise ProjectError(f"Source rows must be an array: {tag}")
            node.extend(decode_value(key, row, fields[key]) for row in item)
        else:
            node.append(decode_value(key, item, fields[key]))
    if kind in shapes():
        order_children(node, kind)
    return node


def encode_properties(
    node: etree._Element, kind: str, exclude: set[str]
) -> dict[str, Any]:
    fields = properties(kind)
    result = {}
    for child in node:
        key = str(child.tag)
        if key in exclude:
            continue
        if key not in fields or key in result:
            raise ProjectError(
                f"Unsupported or duplicate source property: {kind}/{key}"
            )
        result[key] = encode_value(child, fields[key])
    return result

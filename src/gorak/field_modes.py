"""The implicit defaulting mode of fields in readable layouts."""

from lxml import etree

from .xml_shapes import derives, node_kind, shapes
from .xml_text import is_text_node, text_value


def is_implicit_default(node: etree._Element) -> bool:
    """Identify exactly the field scalar omitted by the WML contract."""
    if (
        node.tag != "defaultvalue"
        or node.attrib
        or not is_text_node(node)
        or text_value(node) != "1"
    ):
        return False
    parent = node.getparent()
    return parent is not None and supports_default_mode(native_kind(parent))


def supports_default_mode(kind: str) -> bool:
    return (
        derives(kind, "formfield") or derives(kind, "menufield")
    ) and "defaultvalue" in shapes().get(kind, {})


def native_kind(node: etree._Element) -> str:
    """Resolve typed fields and property wrappers without guessing component types."""
    kind = node_kind(node, str(node.tag))
    if kind in shapes():
        return kind
    parent = node.getparent()
    if parent is None:
        return kind
    if node.tag == "row":
        return parent.findtext("row_class") or kind
    return shapes().get(native_kind(parent), {}).get(str(node.tag), kind)

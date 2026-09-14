"""Legacy expanded-preview WML codec; ordinary nested WML uses contract_source."""

from lxml import etree

from .errors import ProjectError
from .parser import FRAME_MARKUP_CHILDREN, serialize_wml
from .readable_values import XSI, properties, validate_type
from .wml_writer import parse_markup
from .xml_shapes import node_kind, order_children, shape, shapes


def encode_node(node: etree._Element, kind: str) -> etree._Element:
    actual = node_kind(node, kind)
    validate_type(actual, kind)
    kind = actual
    tag = kind if node.tag == "row" and XSI in node.attrib else str(node.tag)
    out = etree.Element(tag)
    for key, value in node.attrib.items():
        if key == XSI:
            if node.tag != "row":
                out.set("_type", value)
        elif key.isidentifier():
            out.set(f"_attribute_{key}", value)
        else:
            raise ProjectError(f"Unsupported markup attribute: {key}")
    if node.tag == "script":
        out.text = etree.CDATA(node.text or "")
        return out
    if node.text is not None and (not len(node) or node.text.strip()):
        out.set("_text", node.text)
    fields = properties(kind)
    seen: set[str] = set()
    for child in node:
        key = str(child.tag)
        if key not in fields or (key in seen and key != "row"):
            raise ProjectError(f"Unsupported markup property: {kind}/{key}")
        seen.add(key)
        if (child.tail or "").strip():
            raise ProjectError("Mixed markup content is unsupported")
        if key != "script" and not len(child) and not child.attrib and key != "row":
            out.set(key, child.text or "")
        else:
            out.append(encode_node(child, fields[key]))
    return out


def decode_node(source: etree._Element, tag: str, kind: str) -> etree._Element:
    out = etree.Element(tag)
    if tag == "row" and source.tag != "row":
        validate_type(str(source.tag), kind)
        kind = str(source.tag)
        out.set(XSI, kind)
    if "_type" in source.attrib:
        validate_type(source.attrib["_type"], kind)
        kind = source.attrib["_type"]
        out.set(XSI, kind)
    if tag == "script":
        if source.attrib or len(source):
            raise ProjectError("A script accepts only text or CDATA")
        out.text = etree.CDATA(source.text or "")
        return out
    if (source.text or "").strip() or (source.tail or "").strip():
        raise ProjectError("Only scripts accept literal markup text")
    fields = properties(kind)
    for key, value in source.attrib.items():
        if key == "_type":
            continue
        if key.startswith("_attribute_"):
            out.set(key.removeprefix("_attribute_"), value)
        elif key == "_text":
            out.text = value
        elif key in fields:
            if fields[key] in shapes() and value:
                raise ProjectError(
                    f"Structured markup property requires an element: {key}"
                )
            etree.SubElement(out, key).text = value
        else:
            raise ProjectError(f"Unsupported markup attribute: {kind}/{key}")
    for child in source:
        key = str(child.tag)
        if key in fields:
            out.append(decode_node(child, key, fields[key]))
        elif "row" in fields and key in shapes():
            out.append(decode_node(child, "row", fields["row"]))
        else:
            raise ProjectError(f"Unsupported markup child: {kind}/{key}")
    names = [c.tag for c in out if c.tag != "row"]
    if len(names) != len(set(names)):
        raise ProjectError(f"Duplicate markup property in {kind}")
    if kind in shapes():
        order_children(out, kind)
    return out


def encode_markup(component: etree._Element) -> str:
    root = etree.Element("frame", source_format="2")
    fields = shape("framesource")
    for child in component:
        if child.tag in FRAME_MARKUP_CHILDREN:
            root.append(encode_node(child, fields[str(child.tag)]))
    return serialize_wml(root) + "\n"


def decode_markup(text: str) -> list[etree._Element]:
    root = parse_markup(text)
    if root.tag != "frame" or dict(root.attrib) != {"source_format": "2"}:
        raise ProjectError("Self-contained frame markup requires source_format=2")
    if (root.text or "").strip():
        raise ProjectError("Unexpected frame root text")
    result = []
    seen = set()
    for child in root:
        key = str(child.tag)
        if key not in FRAME_MARKUP_CHILDREN or key in seen:
            raise ProjectError(f"Unsupported or duplicate frame section: {key}")
        seen.add(key)
        result.append(decode_node(child, key, shape("framesource")[key]))
    return result

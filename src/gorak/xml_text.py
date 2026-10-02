"""Lossless text at the OpenROAD XML boundary.

XML 1.0 cannot carry some characters present in 4GL source. OpenROAD represents
these with processing instructions, interleaved with ordinary text/CDATA.
"""

import re

from lxml import etree

from .errors import ProjectError

TARGET = "ingres_invalidxmlchar"
INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def is_text_node(node: etree._Element) -> bool:
    """Whether a property contains text rather than nested XML elements."""
    return all(not isinstance(child.tag, str) for child in node)


def text_value(node: etree._Element | None) -> str:
    if node is None:
        return ""
    parts = [node.text or ""]
    for child in node:
        if isinstance(child, etree._ProcessingInstruction):
            if child.target != TARGET:
                raise ProjectError(
                    f"Unsupported XML processing instruction: {child.target}"
                )
            raw = (child.text or "").strip()
            if not re.fullmatch(r"[0-9]+", raw) or len(raw) > 7:
                raise ProjectError("Invalid ingres_invalidxmlchar code point")
            code = int(raw)
            if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                raise ProjectError("Invalid ingres_invalidxmlchar code point")
            character = chr(code)
            if not INVALID_XML.fullmatch(character):
                raise ProjectError(
                    "ingres_invalidxmlchar requires an XML-invalid character"
                )
            parts.append(character)
        elif not isinstance(child, etree._Comment):
            raise ProjectError(f"Expected XML text, found nested element: {child.tag}")
        parts.append(child.tail or "")
    return "".join(parts)


def find_text(node: etree._Element, path: str) -> str | None:
    child = node.find(path)
    return None if child is None else text_value(child)


def validate_instructions(node: etree._Element) -> None:
    """Refuse unknown instructions even in otherwise unprojected properties."""
    for instruction in node.iter():
        if isinstance(instruction, etree._ProcessingInstruction):
            parent = instruction.getparent()
            if parent is None or not is_text_node(parent):
                raise ProjectError(
                    "XML processing instructions require a text property"
                )
            text_value(parent)


def set_text(node: etree._Element, value: str, *, cdata: bool = False) -> None:
    """Replace a scalar's contents with legal XML, retaining attributes/tail."""
    if not is_text_node(node):
        raise ProjectError(f"Cannot replace structured XML property: {node.tag}")
    # Validate existing instructions before replacing them.
    text_value(node)
    parts = INVALID_XML.split(value)
    invalid = INVALID_XML.findall(value)
    if any(0xD800 <= ord(character) <= 0xDFFF for character in invalid):
        raise ProjectError("Surrogate code points are not supported in source text")
    for child in list(node):
        node.remove(child)
    # XML parsers normalize literal CR, including inside CDATA. Plain text
    # serialization emits character references, including on PI tails.
    cdata = cdata and "\r" not in value
    node.text = etree.CDATA(parts[0]) if cdata else parts[0]
    for character, part in zip(invalid, parts[1:], strict=True):
        instruction = etree.ProcessingInstruction(TARGET, str(ord(character)))
        node.append(instruction)
        instruction.tail = etree.CDATA(part) if cdata else part

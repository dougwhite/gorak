"""Parse explicit frame markup with XML safety checks."""

from lxml import etree

from .source_xml import from_bytes
from .xml_text import validate_instructions

XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"


def parse_markup(text: str) -> etree._Element:
    tree = from_bytes(text.encode("utf-8"))
    validate_instructions(tree)
    return tree

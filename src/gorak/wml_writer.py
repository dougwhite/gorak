"""Parse explicit frame markup with XML safety checks."""

from lxml import etree

from .errors import ProjectError
from .xml_text import validate_instructions

XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"


def parse_markup(text: str) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, strip_cdata=False)
    tree = etree.fromstring(text.encode("utf-8"), parser)
    if tree.getroottree().docinfo.doctype:
        raise ProjectError("Frame markup must not contain a document type")
    validate_instructions(tree)
    return tree

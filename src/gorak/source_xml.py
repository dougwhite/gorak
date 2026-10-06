"""Large local source documents, with external entities disabled and size bounds."""

from io import BytesIO
from pathlib import Path

from lxml import etree

from .errors import ProjectError

MAX_DOCUMENT_BYTES = 512 * 1024 * 1024
MAX_DEPTH = 256


def read_tree(path: Path | str) -> etree._ElementTree:
    path = Path(path)
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ProjectError("Source XML exceeds the 512 MiB document limit")
    with path.open("rb") as stream:
        return parse_stream(stream)


def from_bytes(data: bytes) -> etree._Element:
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ProjectError("Source XML exceeds the 512 MiB document limit")
    return parse_stream(BytesIO(data)).getroot()


def parse_stream(stream: object) -> etree._ElementTree:
    # huge_tree permits embedded bitmap text larger than libxml2's 10 MB limit.
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, strip_cdata=False, huge_tree=True
    )
    tree = etree.parse(stream, parser)
    if tree.docinfo.doctype:
        raise ProjectError("Source XML must not contain a document type declaration")
    stack = [(tree.getroot(), 1)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise ProjectError("Source XML exceeds the nesting limit")
        stack.extend((child, depth + 1) for child in node)
    return tree

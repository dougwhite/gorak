"""Large local source documents, with external entities disabled and size bounds."""

from collections.abc import Iterator
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


def application_children(path: Path) -> Iterator[etree._Element]:
    """Read a native application a component at a time, retaining XML text/PI.

    Callers must exhaust a validation pass before installing any projected source.
    Each yielded subtree is detached, so retaining it never retains the application.
    """
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ProjectError("Source XML exceeds the 512 MiB document limit")
    with path.open("rb") as stream:
        context = etree.iterparse(
            stream,
            events=("start", "end"),
            resolve_entities=False,
            no_network=True,
            strip_cdata=False,
            huge_tree=True,
        )
        depth = 0
        for event, node in context:
            if event == "start":
                depth += 1
                if depth > MAX_DEPTH:
                    raise ProjectError("Source XML exceeds the nesting limit")
                if depth == 1:
                    if node.getroottree().docinfo.doctype:
                        raise ProjectError(
                            "Source XML must not contain a document type declaration"
                        )
                    if node.tag != "OPENROAD":
                        raise ProjectError("Unsupported export document structure")
            else:
                if depth == MAX_DEPTH and len(node):
                    raise ProjectError("Source XML exceeds the nesting limit")
                if depth == 2:
                    if node.tag not in {"APPLICATION", "COMPONENT"}:
                        raise ProjectError("Unsupported export document structure")
                    parent = node.getparent()
                    assert parent is not None
                    parent.remove(node)
                    yield node
                elif depth == 1 and len(node):
                    # Comments, PIs and entity nodes are not valid top-level items.
                    raise ProjectError("Unsupported export document structure")
                depth -= 1

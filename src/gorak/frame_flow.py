"""Preserve native frame-generation graphs inside frame WML.

Native frmflow graphs are not described by openroad.xsd. Keep their structure
without applying layout/default rules to generation metadata.
"""

from copy import deepcopy

from lxml import etree

from .errors import ProjectError
from .xml_text import is_text_node, set_text, text_value

XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"


def validate_graph(node: etree._Element) -> None:
    definitions: set[str] = set()
    references: set[str] = set()
    for child in node.iter():
        if not isinstance(child.tag, str):
            continue
        if ":" in child.get(XSI, ""):
            raise ProjectError("Qualified frmflow type names are unsupported")
        oid, ref = child.get("oid"), child.get("oidref")
        if oid is not None:
            if not oid or oid in definitions or ref is not None:
                raise ProjectError("Invalid or duplicate frmflow object ID")
            definitions.add(oid)
        if ref is not None:
            if not ref or len(child) or (child.text or ""):
                raise ProjectError("Invalid frmflow object reference")
            references.add(ref)
    if references - definitions:
        raise ProjectError("Unresolved or external frmflow object reference")
    # IDs outside the graph cannot safely be joined to a reconstructed graph.
    root = node
    while root.getparent() is not None and root.tag != "COMPONENT":
        root = root.getparent()
    graph = set(node.iter())
    if any(
        child not in graph
        and (child.get("oid") in definitions or child.get("oidref") in definitions)
        for child in root.iter()
        if isinstance(child.tag, str)
    ):
        raise ProjectError("frmflow object IDs overlap references outside the graph")


def validate_tree(node: etree._Element) -> None:
    for child in node.iter():
        if not isinstance(child.tag, str):
            continue
        if child.tag.startswith("{"):
            raise ProjectError("Namespaced frmflow elements are unsupported")
        if not is_text_node(child) and (
            (child.text or "").strip() or any((c.tail or "").strip() for c in child)
        ):
            raise ProjectError("Mixed frmflow content is unsupported")
        if is_text_node(child):
            text_value(child)
    validate_graph(node)


def validate_component_flow(component: etree._Element) -> None:
    nodes = component.findall("frmflow")
    if len(nodes) > 1:
        raise ProjectError("Duplicate frmflow properties are unsupported")
    if not nodes:
        return
    from .parser import FRAME_COMPONENT_TYPES

    if component.get(XSI) not in FRAME_COMPONENT_TYPES:
        raise ProjectError("Only frames support frmflow metadata")
    validate_tree(nodes[0])


def flow_markup(node: etree._Element) -> etree._Element:
    validate_tree(node)
    return deepcopy(node)


def serialize_flow(node: etree._Element, indent: int) -> str:
    """Indent element-only containers without modifying any scalar or PI text."""
    copied = deepcopy(node)

    def formatting(element: etree._Element, level: int) -> None:
        if is_text_node(element):
            return
        element.text = "\n" + "  " * (level + 1)
        for i, child in enumerate(element):
            formatting(child, level + 1)
            child.tail = "\n" + "  " * (level if i == len(element) - 1 else level + 1)

    formatting(copied, indent)
    return "  " * indent + str(
        etree.tostring(copied, encoding="unicode", with_tail=False)
    )


def canonical_ids(node: etree._Element) -> None:
    """Normalize ID labels by definition order, retaining sharing and references."""
    validate_graph(node)
    ids = {
        child.get("oid"): str(i)
        for i, child in enumerate(node.iter())
        if child.get("oid") is not None
    }
    for child in node.iter():
        for attribute in ("oid", "oidref"):
            if attribute in child.attrib:
                child.set(attribute, ids[child.get(attribute)])


def flow_signature(component: etree._Element) -> object:
    """Compare native structure directly, independently of WML projection."""
    from .importer import signature

    result = []
    for original in component.findall("frmflow"):
        validate_graph(original)
        node = deepcopy(original)
        canonical_ids(node)
        # Text instructions and character references are equivalent spellings.
        for child in list(node.iter()):
            if isinstance(child.tag, str) and is_text_node(child):
                set_text(child, text_value(child))
        result.append(signature(node))
    return result

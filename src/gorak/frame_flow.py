"""Preserve ordered frame-generation metadata independently of schema coverage.

Native frmflow graphs are not described by openroad.xsd. Keep their named
elements, scalar text, attributes and ordered children in a versioned JSON tree.
Refuse mixed content or references outside this graph rather than dropping data.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from lxml import etree

from .errors import ProjectError
from .xml_text import is_text_node, set_text, text_value

XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"


def flow_path(source: Path) -> Path:
    return source.with_suffix(".frmflow.json")


def scalar_flow(node: etree._Element) -> bool:
    return not node.attrib and is_text_node(node) and bool(text_value(node))


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


def encode_node(node: etree._Element) -> dict[str, Any]:
    if not isinstance(node.tag, str) or node.tag.startswith("{"):
        raise ProjectError("Unsupported frmflow element or comment")
    result: dict[str, Any] = {"tag": node.tag}
    if node.attrib:
        result["attributes"] = dict(node.attrib)
    if is_text_node(node):
        result["text"] = text_value(node)
    else:
        if (node.text or "").strip() or any((c.tail or "").strip() for c in node):
            raise ProjectError("Mixed frmflow content is unsupported")
        result["children"] = [encode_node(child) for child in node]
    return result


def encode_flow(component: etree._Element) -> dict[str, Any] | None:
    nodes = component.findall("frmflow")
    if len(nodes) > 1:
        raise ProjectError("Duplicate frmflow properties are unsupported")
    if not nodes:
        return None
    from .parser import FRAME_COMPONENT_TYPES

    if component.get(XSI) not in FRAME_COMPONENT_TYPES:
        raise ProjectError("Only frames support frmflow metadata")
    node = nodes[0]
    validate_graph(node)
    # Retain the existing scalar TOML spelling as a separate control.
    if scalar_flow(node):
        return None
    return {"version": 1, "frmflow": encode_node(node)}


def decode_node(value: Any) -> etree._Element:
    if (
        not isinstance(value, dict)
        or set(value) - {"tag", "attributes", "text", "children"}
        or not isinstance(value.get("tag"), str)
        or value["tag"].startswith("{")
        or ("text" in value) == ("children" in value)
    ):
        raise ProjectError("Expected frmflow node with tag and text or children")
    node = etree.Element(value["tag"])
    attributes = value.get("attributes", {})
    if not isinstance(attributes, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in attributes.items()
    ):
        raise ProjectError("Expected frmflow string attributes")
    node.attrib.update(attributes)
    if "text" in value:
        if not isinstance(value["text"], str):
            raise ProjectError("Expected frmflow scalar text")
        set_text(node, value["text"])
    else:
        if not isinstance(value["children"], list) or not value["children"]:
            raise ProjectError("Expected nonempty ordered frmflow children")
        node.extend(decode_node(child) for child in value["children"])
    return node


def read_flow(source: Path) -> etree._Element | None:
    path = flow_path(source)
    if not path.exists():
        return None
    from .query_metadata import unique_object

    try:
        data = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
        if (
            not isinstance(data, dict)
            or set(data) != {"version", "frmflow"}
            or type(data["version"]) is not int
            or data["version"] != 1
        ):
            raise ProjectError("Expected version 1 frmflow metadata")
        if data["frmflow"] is None:
            return None
        node = decode_node(data["frmflow"])
        if node.tag != "frmflow":
            raise ProjectError("Expected frmflow root")
        validate_graph(node)
        return node
    except (ValueError, TypeError, OSError, ProjectError) as ex:
        raise ProjectError(f"Invalid frmflow metadata {path}: {ex}") from ex


def write_flow(source: Path, value: dict[str, Any] | None) -> None:
    path = flow_path(source)
    if value is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(
            json.dumps(value, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def overlay_flow(node: etree._Element, source: Path) -> None:
    previous = node.find("frmflow")
    path = flow_path(source)
    if not path.is_file():
        if previous is not None and not scalar_flow(previous):
            raise ProjectError(
                f"Missing frmflow metadata {path}; re-export the component. "
                'To remove explicitly, use {"version": 1, "frmflow": null}.'
            )
        return
    from .parser import FRAME_COMPONENT_TYPES, parse_w4gl

    if node.get(XSI) not in FRAME_COMPONENT_TYPES:
        raise ProjectError("Only frames support frmflow metadata")
    if "frmflow" in parse_w4gl(source.read_text(encoding="utf-8"), source.stem).props:
        raise ProjectError("frmflow cannot appear in both TOML and a sidecar")
    desired = read_flow(source)
    for child in node.findall("frmflow"):
        node.remove(child)
    if desired is not None:
        node.append(desired)
        validate_graph(desired)
    from .xml_shapes import order_children

    order_children(node, str(node.get(XSI)))


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
    """Compare native structure directly, independently of JSON/source projection."""
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

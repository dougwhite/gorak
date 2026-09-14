"""Overlay frame-default property edits while retaining native grouping and rows."""

from typing import Any

from lxml import etree

from .errors import ProjectError
from .field_defaults import group_name, parse_field_defaults_node
from .wml_writer import value_node
from .xml_shapes import node_kind, order_children, shape


def overlay_properties(
    node: etree._Element, old: dict[str, Any], new: dict[str, Any]
) -> None:
    kind = node_kind(node, "matrixfield")
    for key in set(old) | set(new):
        if old.get(key) == new.get(key):
            continue
        if key not in shape(kind):
            raise ProjectError(f"Unsupported field default property: {kind}/{key}")
        existing = node.findall(key)
        if len(existing) > 1:
            raise ProjectError(f"Ambiguous field default property: {kind}/{key}")
        for child in existing:
            node.remove(child)
        if key in new:
            node.append(value_node(key, new[key]))
    order_children(node, kind)


def overlay_defaults(node: etree._Element, desired: dict[str, Any]) -> None:
    container = node.find("fielddefaults")
    if container is None:
        if desired:
            raise ProjectError(
                "Adding frame-default groups requires an exported baseline"
            )
        return
    original = parse_field_defaults_node(container)
    if original == desired:
        return
    if set(desired) != set(original):
        raise ProjectError("Frame-default edits must retain the existing structure")
    old_common = original["common_model_container"]
    new_common = desired["common_model_container"]
    if new_common.get("type") != old_common["type"]:
        raise ProjectError("Changing the frame-default container type is unsupported")
    old_styles = original["field_styles"]
    new_styles = desired["field_styles"]
    if [(s["group"], s["type"]) for s in old_styles] != [
        (s["group"], s["type"]) for s in new_styles
    ]:
        raise ProjectError("Frame-default edits must retain existing style identities")
    counts: dict[str, int] = {}
    style_index = 0
    for row in container.findall("row"):
        group = group_name(row, counts)
        overlay_properties(row, old_common["properties"], new_common["properties"])
        for field in row.findall("childfields/row"):
            kind = node_kind(field, "")
            if not kind:
                continue
            old_style = old_styles[style_index]
            new_style = new_styles[style_index]
            if (group, kind) != (old_style["group"], old_style["type"]):
                raise ProjectError("Unrepresented frame-default style")
            overlay_properties(field, old_style["properties"], new_style["properties"])
            style_index += 1
    if parse_field_defaults_node(container) != desired:
        raise ProjectError(
            "Frame-default edits do not round-trip through the source format"
        )

"""Verify OpenROAD Windows geometry at its observed 96-unit logical pixel grid.

Coordinates are exported in thousandths of an inch. Only the four geometry
properties in frame markup have pixel equivalence. Field default modes also use
the WML contract's implicit DV_SYSTEM rule; all other XML remains exact.
Observed native baselines retain exact pre-write conflict checks. Planning and
accepted-submission baselines allow the observed native pixel equivalence.
"""

from copy import deepcopy

from lxml import etree

from .field_modes import is_implicit_default
from .native_normalization import opaque_descendant
from .parser import (
    FIELD_TEMPLATE_CHILDREN,
    FRAME_MARKUP_CHILDREN,
    NS,
    WML_COMPONENT_TYPES,
    parse_component_node,
)
from .xml_shapes import derives, node_kind

COORDINATES = {"xleft", "ytop", "width", "height"}


def pixel(value: str) -> int:
    number = int(value)
    return (abs(number) * 96 + 500) // 1000 * (-1 if number < 0 else 1)


def geometry_signature(node: etree._Element) -> object:
    from .importer import signature

    copied = deepcopy(node)
    if copied.get(f"{{{NS['xsi']}}}type") not in WML_COMPONENT_TYPES:
        return signature(copied)
    for section in copied:
        if section.tag not in FRAME_MARKUP_CHILDREN | FIELD_TEMPLATE_CHILDREN:
            continue
        for child in list(section.iter()):
            if child.tag in {"extension", "taggedvalues"} or opaque_descendant(child):
                continue
            if is_implicit_default(child):
                parent = child.getparent()
                assert parent is not None
                parent.remove(child)
                continue
            if child.tag not in COORDINATES or len(child) or child.attrib:
                continue
            parent = child.getparent()
            assert parent is not None
            if parent is not section and not derives(
                node_kind(parent, ""), "formfield"
            ):
                continue
            try:
                coordinate = pixel(child.text or "0")
            except ValueError:
                continue
            if coordinate == 0:
                parent.remove(child)
            else:
                child.text = str(coordinate)
    return signature(copied)


def normalized_markup(expected: etree._Element, actual: etree._Element) -> str | None:
    """Return canonical WML only after complete pixel-equivalent XML verification."""
    from .importer import signature

    if signature(expected) == signature(actual):
        return None
    if geometry_signature(expected) != geometry_signature(actual):
        return None
    component = parse_component_node(actual)
    if component.type not in WML_COMPONENT_TYPES:
        return None
    if component.type == "fieldtemplate":
        from .field_templates import encode_layout

        return encode_layout(actual) + "\n"
    from .parser import encode_frame_markup

    return (
        encode_frame_markup(
            [child for child in actual if child.tag in FRAME_MARKUP_CHILDREN],
            explicit=True,
        )
        + "\n"
    )


ZERO_DIMENSIONS = {"rectangleshape": ("width", "height"), "segmentshape": ("width",)}


def explicit_shape_dimensions(root: etree._Element) -> None:
    """Preserve omitted native zeros against nonzero XML-import constructors."""
    from .xml_shapes import order_children

    # Opaque metadata may reuse native type names without being layout fields.
    # Preserve it verbatim, as accepted-baseline tracking does.
    for field in list(root.iter()):
        if field.tag in {"extension", "taggedvalues"} or opaque_descendant(field):
            continue
        kind = field.get(f"{{{NS['xsi']}}}type", "")
        changed = False
        for dimension in ZERO_DIMENSIONS.get(kind, ()):
            if field.find(dimension) is None:
                etree.SubElement(field, dimension).text = "0"
                changed = True
        if changed:
            order_children(field, kind)

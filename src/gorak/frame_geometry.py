"""Verify OpenROAD Windows geometry at its observed 96-unit logical pixel grid.

Coordinates are exported in thousandths of an inch. Only the four geometry
properties in frame markup have this equivalence; all other XML remains exact.
Baseline/database conflict comparisons deliberately do not use this function.
"""

from copy import deepcopy

from lxml import etree

from .parser import FRAME_MARKUP_CHILDREN, NS, encode_wml, parse_component_node
from .xml_shapes import derives, node_kind

COORDINATES = {"xleft", "ytop", "width", "height"}


def pixel(value: str) -> int:
    number = int(value)
    return (abs(number) * 96 + 500) // 1000 * (-1 if number < 0 else 1)


def geometry_signature(node: etree._Element) -> object:
    from .importer import signature

    copied = deepcopy(node)
    if copied.get(f"{{{NS['xsi']}}}type") != "framesource":
        return signature(copied)
    for section in copied:
        if section.tag not in FRAME_MARKUP_CHILDREN:
            continue
        for child in list(section.iter()):
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


def normalized_markup(
    expected: etree._Element, actual: etree._Element, *, complete: bool = False
) -> str | None:
    """Return canonical WML only after complete pixel-equivalent XML verification."""
    from .importer import signature

    if signature(expected) == signature(actual):
        return None
    if geometry_signature(expected) != geometry_signature(actual):
        return None
    component = parse_component_node(actual)
    if component.type != "framesource":
        return None
    if complete:
        from .readable_markup import encode_markup

        return encode_markup(actual)
    # Markup was encoded with the native frame defaults before inheritance.
    markup = encode_wml(component)
    return markup + "\n" if markup is not None else None

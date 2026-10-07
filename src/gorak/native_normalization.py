"""Narrow native XML equivalences for tracking accepted import submissions.

This compares complete XML, independently of the readable source projection.
Collection rows and literal scalar whitespace remain significant.
"""

from copy import deepcopy

from lxml import etree

from .xml_text import is_text_node, set_text, text_value

XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"


def opaque_descendant(node: etree._Element) -> bool:
    return any(
        parent.tag in {"extension", "taggedvalues"} for parent in node.iterancestors()
    )


def explicit_row_types(root: etree._Element) -> None:
    """Resolve native array default types without changing row order or contents."""
    for node in root.iter():
        if opaque_descendant(node):
            continue
        row_class = node.find("row_class")
        rows = node.findall("row")
        if (
            row_class is not None
            and rows
            and not row_class.attrib
            and is_text_node(row_class)
            and text_value(row_class)
        ):
            for row in rows:
                if XSI not in row.attrib:
                    row.set(XSI, text_value(row_class))
            node.remove(row_class)


def signature(root: etree._Element, *, pixel_geometry: bool = False) -> object:
    from .importer import signature as raw_signature

    node = deepcopy(root)
    explicit_row_types(node)
    for child in list(node.iter()):
        if not isinstance(child.tag, str) or opaque_descendant(child):
            continue
        parent = child.getparent()
        if parent is None:
            continue
        if child.tag == "script":
            set_text(child, text_value(child).strip(" \t\r\n"), cdata=True)
        if (
            child.tag in {"width", "height"}
            and not child.attrib
            and is_text_node(child)
            and text_value(child) == "0"
            and (
                parent.get(XSI) == "rectangleshape"
                or (parent.get(XSI) == "segmentshape" and child.tag == "width")
            )
        ):
            parent.remove(child)
            continue
        if (
            child.tag == "defaultvalue"
            and not child.attrib
            and is_text_node(child)
            and text_value(child) == "1"
        ):
            parent.remove(child)
        elif (
            child.tag
            in {
                "versshortremarks",
                "defaultstring",
                "script",
                "extension",
                "taggedvalues",
                "queries",
                "fielddefaults",
                "appflags",
            }
            and not child.attrib
            and not len(child)
            and not text_value(child)
            and not (
                child.tag == "script" and parent.find("macro_vars/row") is not None
            )
        ):
            parent.remove(child)
    # Native versions can emit named properties in a different schema order.
    # Stable sorting preserves every repeated row's relative position. Opaque
    # metadata and mixed text retain their original ordering.
    for field in node.iter():
        if field.tag in {"extension", "taggedvalues"} or opaque_descendant(field):
            continue
        if (
            all(isinstance(child.tag, str) for child in field)
            and not (field.text or "").strip()
            and all(not (child.tail or "").strip() for child in field)
        ):
            field[:] = sorted(field, key=lambda child: str(child.tag))
    if pixel_geometry:
        from .frame_geometry import geometry_signature

        return geometry_signature(node)
    return raw_signature(node)

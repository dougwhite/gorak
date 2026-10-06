"""Reusable native field layouts and validation for newly supported components."""

from pathlib import Path

from lxml import etree

from .errors import ProjectError
from .xml_text import find_text, is_text_node


def validate_component(node: etree._Element, kind: str) -> None:
    """Refuse unrepresented metadata instead of flattening structured values."""
    from .parser import FIELD_TEMPLATE_CHILDREN
    from .xml_shapes import shape

    seen: set[str] = set()
    for child in node:
        key = str(child.tag)
        if key not in shape(kind) or key in seen:
            raise ProjectError(f"Unsupported or duplicate {kind} property: {key}")
        seen.add(key)
        if kind == "fieldtemplate" and key in FIELD_TEMPLATE_CHILDREN:
            continue
        if key == "extension":
            if child.attrib or len(child) or (child.text or "").strip():
                raise ProjectError(f"Unsupported {kind} extension metadata")
        elif key == "taggedvalues":
            if (
                child.attrib
                or (child.text or "").strip()
                or any((row.tail or "").strip() for row in child)
            ):
                raise ProjectError(f"Unsupported {kind} tagged values")
            names: set[str] = set()
            row_class_seen = False
            for row in child:
                if row.tag == "row_class":
                    if (
                        row_class_seen
                        or row.attrib
                        or len(row)
                        or row.text != "taggedvalue"
                    ):
                        raise ProjectError(f"Unsupported {kind} tagged values")
                    row_class_seen = True
                    continue
                name = find_text(row, "name")
                if (
                    row.tag != "row"
                    or row.attrib
                    or (row.text or "").strip()
                    or any((c.tail or "").strip() for c in row)
                    or [c.tag for c in row] != ["name", "value"]
                    or any(c.attrib or not is_text_node(c) for c in row)
                    or name is None
                    or name.casefold() in names
                ):
                    raise ProjectError(f"Unsupported {kind} tagged values")
                names.add(name.casefold())
        elif child.attrib or not is_text_node(child):
            raise ProjectError(f"Unsupported structured {kind} property: {key}")


def encode_layout(node: etree._Element) -> str:
    from .parser import (
        FIELD_TEMPLATE_CHILDREN,
        MarkupDefaultsIndex,
        frame_markup_element,
        serialize_wml,
    )

    root = etree.Element("fieldtemplate")
    index = MarkupDefaultsIndex({}, {}, explicit=True)
    for child in node:
        if child.tag in FIELD_TEMPLATE_CHILDREN:
            root.append(frame_markup_element(child, index))
    return serialize_wml(root)


def decode_layout(path: Path) -> list[etree._Element]:
    from .contract_source import markup_node
    from .image_assets import resolve
    from .parser import FIELD_TEMPLATE_CHILDREN, MarkupDefaultsIndex
    from .wml_writer import parse_markup

    wml = path.with_suffix(".wml")
    if not wml.is_file():
        raise ProjectError("Field template requires a WML source file")
    root = parse_markup(wml.read_text())
    if root.tag != "fieldtemplate" or root.attrib or (root.text or "").strip():
        raise ProjectError(
            "Field template markup requires a plain <fieldtemplate> root"
        )
    resolve(root, path.parent)
    seen: set[str] = set()
    result = []
    for child in root:
        tag = str(child.tag)
        if tag not in FIELD_TEMPLATE_CHILDREN or tag in seen:
            raise ProjectError(
                f"Unsupported or duplicate field template section: {tag}"
            )
        seen.add(tag)
        result.append(
            markup_node(
                child, tag, "formfield", MarkupDefaultsIndex({}, {}, explicit=True)
            )
        )
    return result

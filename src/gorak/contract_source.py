"""Reconstruct the established compact source contract without XML companions."""

from pathlib import Path

from lxml import etree

from .errors import ProjectError
from .parser import (
    FRAME_COMPONENT_TYPES,
    FRAME_MARKUP_CHILDREN,
    MAINBAR_MARKUP_CHILDREN,
    NS,
    MarkupDefaultsIndex,
    parse_w4gl,
)
from .wml_writer import XSI, parse_markup
from .xml_shapes import derives, order_children, shape, shapes
from .xml_text import is_text_node, set_text, text_value


def markup_node(
    source: etree._Element, tag: str, kind: str, index: MarkupDefaultsIndex
) -> etree._Element:
    if tag == "script" or kind.startswith("xs:"):
        if source.attrib or not is_text_node(source) or (source.tail or "").strip():
            raise ProjectError(
                "Text properties accept only text, CDATA, or character instructions"
            )
        result = etree.Element(tag)
        set_text(result, text_value(source), cdata=tag == "script")
        return result
    if (source.text or "").strip() or (source.tail or "").strip():
        raise ProjectError("Only scripts accept literal markup text")
    if source.tag == "protofield":
        declared = source.get("type")
        if declared is not None:
            if not derives(declared, kind):
                raise ProjectError("Unsupported column prototype type")
            kind = declared
        else:
            keys = (set(source.attrib) - {"gorak_style"}) | {
                str(child.tag) for child in source
            }
            candidates = [
                candidate
                for candidate in ("entryfield", "optionfield", "togglefield")
                if keys <= shape(candidate).keys()
            ]
            if len(candidates) != 1:
                raise ProjectError(
                    "Ambiguous or unsupported column prototype properties"
                )
            kind = candidates[0]
    if str(source.tag) in shapes() and derives(str(source.tag), kind):
        kind = str(source.tag)
    node = etree.Element(tag)
    if (tag == "row" and source.tag != "row") or source.tag == "protofield":
        node.set(XSI, kind)
    if source.get("gorak_style") is not None:
        raise ProjectError("gorak_style is unsupported; re-export the application")
    fields = shape(kind)
    for key, value in source.attrib.items():
        if key == "type" and source.tag == "protofield":
            continue
        if key in {"row", "column"} and tag == "row":
            node.set(key, value)
            continue
        if key not in fields or (fields[key] in shapes() and value != ""):
            raise ProjectError(
                f"Unsupported markup property: {source.tag} ({kind})/{key}"
            )
        for previous in node.findall(key):
            node.remove(previous)
        set_text(etree.SubElement(node, key), value)
    seen: set[str] = set()
    names: set[str] = set()
    for child in source:
        key = str(child.tag)
        if key in fields:
            if (key in seen or key in source.attrib) and key != "row":
                raise ProjectError(f"Duplicate markup property: {key}")
            seen.add(key)
            if key != "row":
                for previous in node.findall(key):
                    node.remove(previous)
            node.append(markup_node(child, key, fields[key], index))
        else:
            container_name = next(
                (name for name in ("childfields", "childmenufields") if name in fields),
                None,
            )
            base = "formfield" if container_name == "childfields" else "menufield"
            if container_name is None or not derives(key, base):
                raise ProjectError(f"Unsupported markup child: {kind}/{key}")
            name = child.get("name", "").casefold()
            if name and name in names:
                raise ProjectError(f"Duplicate sibling field name: {name}")
            names.add(name)
            container = node.find(container_name)
            if container is None:
                container = etree.SubElement(node, container_name)
                etree.SubElement(container, "row_class").text = base
            container.insert(len(container) - 1, markup_node(child, "row", key, index))
    order_children(node, kind)
    return node


def decode_component(path: Path) -> etree._Element:
    from .component_edits import SUPPORTED_TYPES, overlay_metadata
    from .importer import validate_name

    validate_name(path.stem)
    source = parse_w4gl(path.read_text(), path.stem)
    kind = source.type
    if kind not in SUPPORTED_TYPES:
        raise ProjectError(f"Unsupported component type: {kind}")
    node = etree.Element("COMPONENT", name=path.stem, nsmap=NS)
    node.set(XSI, kind)
    overlay_metadata(node, path)
    if kind in FRAME_COMPONENT_TYPES:
        if not path.with_suffix(".wml").is_file():
            raise ProjectError("Frame requires a WML source file")
        from . import native_styles

        if "fielddefaults" in source.props:
            raise ProjectError(
                "Inline field defaults are unsupported; re-export the application"
            )
        node.append(native_styles.decode(native_styles.frame_styles(path)))
        index = MarkupDefaultsIndex({}, {}, explicit=True)
        markup = parse_markup(path.with_suffix(".wml").read_text())
        if markup.tag != "frame" or markup.attrib or (markup.text or "").strip():
            raise ProjectError("Frame markup requires a plain <frame> root")
        seen: set[str] = set()
        for section in markup:
            tag = str(section.tag)
            if tag not in FRAME_MARKUP_CHILDREN or tag in seen:
                raise ProjectError(f"Unsupported or duplicate frame section: {tag}")
            seen.add(tag)
            if tag in MAINBAR_MARKUP_CHILDREN:
                wrapper = etree.SubElement(node, tag)
                wrapper.append(markup_node(section, "row", "mainbar", index))
                etree.SubElement(wrapper, "row_class").text = "mainbar"
            else:
                node.append(markup_node(section, tag, shape(kind)[tag], index))
        if "topform" not in seen:
            raise ProjectError("Frame requires a topform section")
    order_children(node, kind)
    return node


def equivalent(
    left: etree._Element, right: etree._Element, *, exact_styles: bool = True
) -> bool:
    """Compare the supported readable contract; retain exact XML drift gates."""
    from .importer import signature
    from .parser import (
        FRAME_MARKUP_CHILDREN,
        frame_markup_element,
        parse_component_node,
    )

    if exact_styles:
        from .native_styles import encode

        lstyle, rstyle = left.find("fielddefaults"), right.find("fielddefaults")
        if (lstyle is None) != (rstyle is None):
            return False
        if (
            lstyle is not None
            and rstyle is not None
            and encode(lstyle) != encode(rstyle)
        ):
            return False
    if parse_component_node(left) != parse_component_node(right):
        return False
    # Do not let default suppression (or style selection) hide changed native
    # scalar properties. Keep bitmap whitespace normalization from the parser.
    empty = MarkupDefaultsIndex({}, {}, explicit=exact_styles)

    def effective_markup(node: etree._Element) -> list[object]:
        return [
            signature(frame_markup_element(child, empty))
            for child in node
            if child.tag in FRAME_MARKUP_CHILDREN
        ]

    return effective_markup(left) == effective_markup(right)

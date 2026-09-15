"""Reconstruct the established compact source contract without XML companions."""

from pathlib import Path
from typing import Any

from lxml import etree

from .errors import ProjectError
from .field_defaults import effective_defaults, read_defaults
from .parser import (
    FRAME_MARKUP_CHILDREN,
    MAINBAR_MARKUP_CHILDREN,
    NS,
    MarkupDefaultsIndex,
    parse_w4gl,
)
from .wml_writer import XSI, parse_markup, value_node
from .xml_shapes import derives, order_children, shape, shapes


def palette_node(defaults: dict[str, Any]) -> etree._Element:
    """Build palette groups from their existing JSON identities and properties."""
    common = defaults.get("common_model_container", {})
    result = etree.Element("fielddefaults")
    groups: dict[str, etree._Element] = {}
    for style in defaults.get("field_styles", []):
        group = style["group"]
        if group not in groups:
            row = etree.SubElement(result, "row")
            kind = common.get("type") or "matrixfield"
            row.set(XSI, kind)
            for key, value in common.get("properties", {}).items():
                row.append(value_node(key, value))
            etree.SubElement(row, "clienttext").text = (
                group.rsplit(":", 1)[0] if group.rsplit(":", 1)[-1].isdigit() else group
            )
            children = etree.SubElement(row, "childfields")
            etree.SubElement(children, "row_class").text = "formfield"
            groups[group] = children
            order_children(row, kind)
        field = etree.Element("row")
        field.set(XSI, style["type"])
        field.set("row", str(len(groups[group].findall("row")) + 1))
        field.set("column", "1")
        for key, value in style["properties"].items():
            field.append(value_node(key, value))
        order_children(field, style["type"])
        groups[group].insert(len(groups[group]) - 1, field)
    for children in groups.values():
        parent = children.getparent()
        assert parent is not None
        etree.SubElement(parent, "columns").text = "1"
        etree.SubElement(parent, "rows").text = str(len(children.findall("row")))
        order_children(parent, common.get("type") or "matrixfield")
    etree.SubElement(result, "row_class").text = "formfield"
    return result


def markup_node(
    source: etree._Element, tag: str, kind: str, index: MarkupDefaultsIndex
) -> etree._Element:
    if tag == "script":
        if source.attrib or len(source):
            raise ProjectError("Script elements accept only text or CDATA")
        result = etree.Element(tag)
        result.text = etree.CDATA(source.text or "")
        return result
    if (source.text or "").strip() or (source.tail or "").strip():
        raise ProjectError("Only scripts accept literal markup text")
    if source.tag == "protofield":
        keys = (set(source.attrib) - {"gorak_style"}) | {
            str(child.tag) for child in source
        }
        candidates = [
            candidate
            for candidate in ("entryfield", "optionfield", "togglefield")
            if keys <= shape(candidate).keys()
        ]
        if len(candidates) != 1:
            raise ProjectError("Ambiguous or unsupported column prototype properties")
        kind = candidates[0]
    if str(source.tag) in shapes() and derives(str(source.tag), kind):
        kind = str(source.tag)
    node = etree.Element(tag)
    if (tag == "row" and source.tag != "row") or source.tag == "protofield":
        node.set(XSI, kind)
    defaults = index.properties_for_markup(source)
    fields = shape(kind)
    for key, value in defaults.items():
        if (
            isinstance(value, str)
            and key in fields
            and key
            not in {
                "name",
                "script",
                "childfields",
                "childmenufields",
            }
        ):
            node.append(value_node(key, value))
    for key, value in source.attrib.items():
        if key == "gorak_style":
            continue
        if key not in fields or fields[key] in shapes():
            raise ProjectError(
                f"Unsupported markup property: {source.tag} ({kind})/{key}"
            )
        for previous in node.findall(key):
            node.remove(previous)
        etree.SubElement(node, key).text = value
    seen: set[str] = set()
    names: set[str] = set()
    for child in source:
        key = str(child.tag)
        if key in fields:
            if key in seen and key != "row":
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
    if kind == "framesource":
        if not path.with_suffix(".wml").is_file():
            raise ProjectError("Frame requires a WML source file")
        defaults = effective_defaults(
            read_defaults(path.parent.parent / "field_defaults.json"),
            read_defaults(path.parent / "field_defaults.json"),
            source.props.get("fielddefaults", {}),
        )
        node.append(palette_node(defaults))
        index = MarkupDefaultsIndex.from_defaults(defaults)
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


def equivalent(left: etree._Element, right: etree._Element) -> bool:
    """Compare the supported readable contract; retain exact XML drift gates."""
    from .importer import signature
    from .parser import (
        FRAME_MARKUP_CHILDREN,
        frame_markup_element,
        parse_component_node,
    )

    if parse_component_node(left) != parse_component_node(right):
        return False
    # Do not let default suppression (or style selection) hide changed native
    # scalar properties. Keep bitmap whitespace normalization from the parser.
    empty = MarkupDefaultsIndex({}, {})

    def effective_markup(node: etree._Element) -> list[object]:
        return [
            signature(frame_markup_element(child, empty))
            for child in node
            if child.tag in FRAME_MARKUP_CHILDREN
        ]

    return effective_markup(left) == effective_markup(right)

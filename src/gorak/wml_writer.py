"""Edit frame projections over preserved XML, retaining unrepresented structures."""

from pathlib import Path
from typing import Any

from lxml import etree

from .errors import ProjectError
from .parser import (
    FRAME_MARKUP_CHILDREN,
    MAINBAR_MARKUP_CHILDREN,
    NS,
    MarkupDefaultsIndex,
    frame_markup_element,
    parse_component_node,
    serialize_wml,
)
from .xml_shapes import derives, node_kind, order_children, set_scalar, shape, shapes
from .xml_text import is_text_node, set_text, text_value, validate_instructions

XSI = f"{{{NS['xsi']}}}type"


def parse_markup(text: str) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, strip_cdata=False)
    tree = etree.fromstring(text.encode("utf-8"), parser)
    if tree.getroottree().docinfo.doctype:
        raise ProjectError("Frame markup must not contain a document type")
    validate_instructions(tree)
    return tree


def value_node(tag: str, value: Any) -> etree._Element:
    """Decode the existing field-default JSON representation without flattening it."""
    node = etree.Element(tag)
    if isinstance(value, dict):
        if "text" in value:
            set_text(node, str(value["text"]))
        for key, child in value.items():
            if key == "type":
                node.set(XSI, str(child))
            elif key == "attributes":
                node.attrib.update(child)
            elif key == "text":
                continue
            elif isinstance(child, list):
                for row in child:
                    node.append(value_node(key, row))
            else:
                node.append(value_node(key, child))
    elif isinstance(value, (str, int, bool)):
        set_text(node, str(int(value)) if isinstance(value, bool) else str(value))
    else:
        raise ProjectError(f"Unsupported field default value: {tag}")
    return node


def identity(node: etree._Element) -> tuple[str, str | None]:
    return str(node.tag), node.get("name")


def overlay_markup(component: etree._Element, path: Path) -> None:
    """Apply WML edits to existing nodes, plus supported new fields and removals."""
    original = parse_component_node(component)
    if original.markup is None:
        if path.exists():
            raise ProjectError(
                "Cannot attach markup to a component without a frame baseline"
            )
        return
    try:
        edited = parse_markup(path.read_text())
    except (OSError, ValueError, etree.XMLSyntaxError) as ex:
        raise ProjectError(f"Cannot read frame markup: {path}: {ex}") from ex
    if edited.tag != "frame" or edited.attrib or (edited.text or "").strip(" \t\r\n"):
        raise ProjectError("Frame markup requires a plain <frame> root")
    if edited.find("topform") is None:
        raise ProjectError("Frame markup edits must retain the topform section")
    index = MarkupDefaultsIndex.from_defaults(original.props.get("fielddefaults", {}))
    mapping: dict[etree._Element, etree._Element] = {}
    before = etree.Element("frame")
    for section in component:
        if section.tag in FRAME_MARKUP_CHILDREN:
            before.append(frame_markup_element(section, index, mapping))
    projected = before
    before = parse_markup(serialize_wml(projected))
    mapping = {
        decoded: mapping[encoded]
        for encoded, decoded in zip(projected.iter(), before.iter(), strict=True)
        if encoded in mapping
    }
    old_sections = {str(n.tag): n for n in before}
    seen: set[str] = set()
    for supplied in edited:
        tag = str(supplied.tag)
        if tag not in FRAME_MARKUP_CHILDREN or tag in seen:
            raise ProjectError(f"Unsupported or duplicate frame section: {tag}")
        seen.add(tag)
        if tag not in old_sections:
            raise ProjectError(
                f"Adding a frame section requires an exported baseline: {tag}"
            )
        old = old_sections[tag]
        native = mapping[old]
        kind = node_kind(native, shape(original.type)[tag])
        update_element(native, kind, old, supplied, mapping, index)
    for tag, old in old_sections.items():
        if tag not in seen:
            component.remove(mapping[old])


def update_element(
    native: etree._Element,
    kind: str,
    before: etree._Element,
    after: etree._Element,
    mapping: dict[etree._Element, etree._Element],
    index: MarkupDefaultsIndex,
) -> None:
    from .importer import signature

    index.properties_for_markup(after)
    if signature(before) == signature(after):
        return
    if before.tag != after.tag:
        raise ProjectError(
            "Changing a field type requires removing and adding the field"
        )
    if not isinstance(after.tag, str) or (after.tail or "").strip(" \t\r\n"):
        raise ProjectError("Unsupported frame markup content")
    if after.tag == "script":
        if after.attrib or not is_text_node(after):
            raise ProjectError("Script elements accept only text or CDATA")
        previous = text_value(native)
        leading = previous[: len(previous) - len(previous.lstrip(" \t\r\n"))]
        trailing = previous[len(previous.rstrip(" \t\r\n")) :]
        set_text(
            native, leading + text_value(after).strip(" \t\r\n") + trailing, cdata=True
        )
        return
    target = native
    if before.tag in MAINBAR_MARKUP_CHILDREN:
        target = native.find("row")
        if target is None:
            raise ProjectError("Cannot edit an empty mainbar without a row baseline")
        kind = node_kind(target, "mainbar")
    if (after.text or "").strip(" \t\r\n") != (before.text or "").strip(" \t\r\n"):
        raise ProjectError("Only script elements support edited text content")
    defaults = index.properties_for_markup(after)
    changed_defaults: set[str] = set()
    if before.get("gorak_style") != after.get("gorak_style"):
        changed_defaults.update(index.omitted_properties(after, defaults))
        changed_defaults.update(
            index.omitted_properties(before, index.properties_for_markup(before))
        )
    old_values, old_scalar_children = scalar_properties(before, kind)
    new_values, new_scalar_children = scalar_properties(after, kind)
    for key in (set(old_values) | set(new_values) | changed_defaults) - {"gorak_style"}:
        if old_values.get(key) == new_values.get(key) and key not in changed_defaults:
            continue
        value = new_values.get(key)
        if key in native.attrib:
            if key == XSI:
                raise ProjectError("Cannot change a native XML type")
            if value is None:
                native.attrib.pop(key)
            else:
                native.set(key, value)
        else:
            positioned_gravity = key == "gravity" and (
                "xleft" in after.attrib or "ytop" in after.attrib
            )
            if (
                value is None
                and isinstance(defaults.get(key), str)
                and not positioned_gravity
            ):
                value = defaults[key]
            set_scalar(target, kind, key, value)
    old_groups: dict[tuple[str, str | None], list[etree._Element]] = {}
    for child in before:
        if child in old_scalar_children:
            continue
        old_groups.setdefault(identity(child), []).append(child)
    named: set[str] = set()
    replacements: list[tuple[etree._Element, etree._Element]] = []
    for supplied in after:
        if supplied in new_scalar_children:
            continue
        name = supplied.get("name")
        if name:
            if name.casefold() in named:
                raise ProjectError(f"Duplicate sibling field name: {name}")
            named.add(name.casefold())
        group = old_groups.get(identity(supplied), [])
        if group:
            old = group.pop(0)
            child = mapping[old]
            parent = child.getparent()
            assert parent is not None
            child_kind = node_kind(
                child, shape(kind).get(str(child.tag), str(child.tag))
            )
            update_element(child, child_kind, old, supplied, mapping, index)
        else:
            child, parent = new_element(target, kind, supplied, index)
        replacements.append((child, parent))
    # Remove only children represented by the old projection. Opaque rows/properties
    # and array metadata stay in their original containers.
    old_children = [mapping[c] for c in before if c not in old_scalar_children]
    affected: set[etree._Element] = set()
    for child in old_children:
        parent = child.getparent()
        assert parent is not None
        affected.add(parent)
        parent.remove(child)
    for child, parent in replacements:
        parent.append(child)
        affected.add(parent)
    for parent in affected:
        parent_kind = kind if parent is target else shape(kind).get(str(parent.tag))
        if parent_kind is None:
            raise ProjectError(f"Unsupported frame container: {parent.tag}")
        order_children(parent, parent_kind)


def new_element(
    parent: etree._Element,
    kind: str,
    supplied: etree._Element,
    index: MarkupDefaultsIndex,
) -> tuple[etree._Element, etree._Element]:
    tag = str(supplied.tag)
    properties = shape(kind)
    if tag == "script":
        if supplied.attrib or not is_text_node(supplied) or "script" not in properties:
            raise ProjectError("Unsupported new script element")
        child = etree.Element("script")
        set_text(child, text_value(supplied), cdata=True)
        return child, parent
    if tag in properties and properties[tag] in shapes():
        child = etree.Element(tag)
        child_kind = properties[tag]
        container = parent
    elif tag in shapes():
        container_name = next(
            (key for key in ("childfields", "childmenufields") if key in properties),
            None,
        )
        if container_name is None:
            raise ProjectError(f"Cannot add {tag} inside {kind}")
        base = "formfield" if container_name == "childfields" else "menufield"
        if not derives(tag, base):
            raise ProjectError(f"{tag} is not a supported {base}")
        container = parent.find(container_name)
        if container is None:
            container = etree.SubElement(parent, container_name)
            row_class = "formfield" if container_name == "childfields" else "menufield"
            etree.SubElement(container, "row_class").text = row_class
            order_children(parent, kind)
        child = etree.Element("row")
        child.set(XSI, tag)
        child_kind = tag
        # Populate the same default values that the WML encoder suppresses.
        for key, value in index.properties_for_markup(supplied).items():
            if key in shape(tag) and key not in {
                "name",
                "script",
                "childfields",
                "childmenufields",
            }:
                child.append(value_node(key, value))
        # Palette alignment defaults must not override explicitly positioned new
        # controls. In particular FA_CENTERLEFT can move them off the viewport.
        if (
            "xleft" in supplied.attrib or "ytop" in supplied.attrib
        ) and "gravity" not in supplied.attrib:
            for gravity in child.findall("gravity"):
                child.remove(gravity)
        order_children(child, tag)
    else:
        raise ProjectError(f"Unsupported new frame element: {tag}")
    mapping: dict[etree._Element, etree._Element] = {}
    before = frame_markup_element(child, index, mapping)
    update_element(child, child_kind, before, supplied, mapping, index)
    if derives(child_kind, "compositefield") and child.find("defaultvalue") is None:
        set_scalar(child, child_kind, "defaultvalue", "1")
    return child, container


def scalar_properties(
    element: etree._Element, kind: str
) -> tuple[dict[str, str], set[etree._Element]]:
    """Unify scalar WML elements (needed for control characters) and attributes."""
    values = dict(element.attrib)
    children: set[etree._Element] = set()
    fields = shape(kind)
    for child in element:
        key = str(child.tag)
        if key == "script" or key not in fields or fields[key] in shapes():
            continue
        if (
            key in values
            or child.attrib
            or not is_text_node(child)
            or (child.tail or "").strip()
        ):
            raise ProjectError(f"Duplicate or invalid scalar markup property: {key}")
        values[key] = text_value(child)
        children.add(child)
    return values, children

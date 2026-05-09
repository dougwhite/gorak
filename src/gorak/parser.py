"""Parse a small, intentionally conservative subset of OpenROAD XML exports."""

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from typing import Any, cast

import tomlkit
from lxml import etree

from .domain import Application, ApplicationExport, Component, IncludedApplication
from .field_defaults import parse_field_defaults_node

IGNORED_PROPERTIES = {
    "script",
    "startmenu",
    "topform",
    "fielddefaults",
    "attributes",
    "methods",
    "taggedvalues",
}

NS = {
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
MULTILINE_ATTRIBUTE_COUNT = 5


def parse_xml(tree: etree._ElementTree | etree._Element) -> Component:
    """Parse an OpenROAD XML export into a component."""

    node = tree.find(".//COMPONENT")
    if node is None:
        raise ValueError("Missing <COMPONENT> node")

    return parse_component_node(node)


def parse_components_xml(tree: etree._ElementTree | etree._Element) -> list[Component]:
    """Parse top-level components from an OpenROAD XML export."""

    root = xml_root(tree)
    return [parse_component_node(node) for node in root.findall("./COMPONENT")]


def parse_application_xml(tree: etree._ElementTree | etree._Element) -> ApplicationExport:
    """Parse simple application metadata and top-level components."""

    root = xml_root(tree)
    app_node = root.find("./APPLICATION")
    if app_node is None:
        raise ValueError("Missing <APPLICATION> node")

    name = app_node.get("name")
    if name is None:
        raise ValueError("<APPLICATION> node must have a name attribute")

    return ApplicationExport(
        application=Application(
            name=name,
            start_component=first_text(app_node, "proc_start", "procstart"),
            description=first_text(app_node, "short_remark", "versshortremarks"),
            database_name=first_text(app_node, "databasename"),
            database_type=first_text(app_node, "database_type"),
        ),
        components=parse_components_xml(root),
        included_applications=parse_included_applications(app_node),
    )


def parse_included_applications(
    app_node: etree._Element,
) -> list[IncludedApplication]:
    """Parse ordered application includes from full application XML metadata."""

    included_apps = app_node.find("included_apps")
    if included_apps is None:
        return []

    includes: list[IncludedApplication] = []
    for row in included_apps.findall("row"):
        app_name = (row.findtext("appname") or "").strip()
        image = (row.findtext("imgfilename") or "").strip()
        if not app_name or is_force_included_core(app_name, image):
            continue
        if image:
            includes.append({"name": app_name, "image": image})
        else:
            includes.append(app_name)

    return includes


def is_force_included_core(app_name: str, image: str) -> bool:
    """Return whether an include is OpenROAD's automatic core.plb dependency."""

    return app_name.lower() == "core" or image.lower() == "core.plb"


def xml_root(tree: etree._ElementTree | etree._Element) -> etree._Element:
    if isinstance(tree, etree._ElementTree):
        return tree.getroot()

    return tree


def parse_component_node(node: etree._Element) -> Component:
    """Parse a single OpenROAD component node."""

    script_node = node.find("script")
    script = (script_node.text or "").strip() if script_node is not None else None

    name = node.get("name")
    if name is None:
        raise ValueError("<COMPONENT> node must have a name attribute")

    component_type = node.get("{{{}}}type".format(NS["xsi"]))
    if component_type is None:
        raise ValueError("<COMPONENT> node must have an xsi:type attribute")

    props = extract_props(node)
    attributes_node = node.find("attributes")
    if attributes_node is not None:
        props["attributes"] = extract_attributes(attributes_node)

    methods_node = node.find("methods")
    if methods_node is not None:
        props["methods"] = extract_methods(methods_node)

    taggedvalues_node = node.find("taggedvalues")
    if taggedvalues_node is not None:
        props["taggedvalues"] = extract_taggedvalues(taggedvalues_node)

    field_defaults_node = node.find("fielddefaults")
    field_defaults: dict[str, Any] = {}
    if field_defaults_node is not None:
        field_defaults = parse_field_defaults_node(field_defaults_node)
        props["fielddefaults"] = field_defaults

    startmenu_node = node.find("startmenu")
    topform_node = node.find("topform")
    markup = (
        encode_frame_markup(startmenu_node, topform_node, field_defaults)
        if component_type == "framesource" and topform_node is not None
        else None
    )

    return Component(name, component_type, props, script, markup)


def encode_frame_markup(
    startmenu_node: etree._Element | None,
    topform_node: etree._Element,
    field_defaults: dict[str, Any] | None = None,
) -> str:
    """Encode an OpenROAD frame form tree as XML-compatible .wml markup."""

    index = MarkupDefaultsIndex.from_defaults(field_defaults or {})
    frame = etree.Element("frame")
    if startmenu_node is not None:
        frame.append(frame_markup_element(startmenu_node, index))
    frame.append(frame_markup_element(topform_node, index))
    return serialize_wml(frame)


def frame_markup_element(
    node: etree._Element,
    defaults_index: "MarkupDefaultsIndex",
) -> etree._Element:
    tag = node.get(f"{{{NS['xsi']}}}type") if node.tag == "row" else node.tag
    if not tag:
        tag = node.tag

    element = etree.Element(tag)
    copy_markup_attributes(node, element)
    default_properties = defaults_index.properties_for(tag, node)
    for child in node:
        if child.tag in {"childfields", "childmenufields"}:
            append_childfields(element, child, defaults_index)
        elif child.tag == "script":
            script = etree.SubElement(element, "script")
            script.text = etree.CDATA((child.text or "").strip())
        elif len(child) == 0 and not child.attrib:
            value = (child.text or "").strip()
            if should_encode_markup_attribute(child.tag, value, default_properties):
                element.set(child.tag, value)
        else:
            element.append(frame_markup_element(child, defaults_index))

    return element


def append_childfields(
    parent: etree._Element,
    childfields: etree._Element,
    defaults_index: "MarkupDefaultsIndex",
) -> None:
    for row in childfields.findall("row"):
        parent.append(frame_markup_element(row, defaults_index))


def copy_markup_attributes(source: etree._Element, target: etree._Element) -> None:
    for name, value in source.attrib.items():
        if name != f"{{{NS['xsi']}}}type":
            target.set(name, value)


def should_encode_markup_attribute(
    name: str,
    value: str,
    default_properties: dict[str, Any],
) -> bool:
    """Return whether a scalar XML property should appear as a .wml attribute."""

    if name == "name":
        return True

    default_value = default_properties.get(name)
    return not isinstance(default_value, str) or default_value != value


@dataclass(frozen=True)
class MarkupDefaultsIndex:
    """Precomputed field-default candidates used while encoding one frame."""

    common_model_properties: dict[str, Any]
    field_styles: dict[str, list[dict[str, Any]]]

    @classmethod
    def from_defaults(cls, field_defaults: dict[str, Any]) -> "MarkupDefaultsIndex":
        container = field_defaults.get("common_model_container")
        common_model_properties: dict[str, Any] = {}
        if isinstance(container, dict) and isinstance(container.get("properties"), dict):
            common_model_properties = cast(dict[str, Any], container["properties"])

        field_styles: dict[str, list[dict[str, Any]]] = {}
        for style in field_defaults.get("field_styles", []):
            if (
                isinstance(style, dict)
                and isinstance(style.get("type"), str)
                and isinstance(style.get("properties"), dict)
            ):
                field_styles.setdefault(style["type"], []).append(
                    cast(dict[str, Any], style["properties"])
                )

        return cls(common_model_properties, field_styles)

    def properties_for(self, tag: str, node: etree._Element) -> dict[str, Any]:
        """Find the most likely field-default property set for a markup element."""

        if tag == "topform":
            return self.common_model_properties

        candidates = self.field_styles.get(tag, [])
        if not candidates:
            return {}

        scalar_values = {
            child.tag: (child.text or "").strip() for child in node if len(child) == 0
        }
        return max(
            candidates,
            key=lambda properties: matching_default_count(properties, scalar_values),
        )


def matching_default_count(
    default_properties: dict[str, Any],
    scalar_values: dict[str, str],
) -> int:
    return sum(
        1
        for key, value in scalar_values.items()
        if isinstance(default_properties.get(key), str)
        and default_properties.get(key) == value
    )


def serialize_wml(element: etree._Element, indent: int = 0) -> str:
    """Serialize generated markup with multiline attributes for dense elements."""

    attrs = serialized_attributes(element)
    children = list(element)
    text = cast(str | None, element.text)
    padding = "  " * indent

    if not children and not text:
        if use_multiline_attributes(attrs):
            return "\n".join(
                [
                    f"{padding}<{element.tag}",
                    *[f"{padding}  {name}={quoted_xml_attr(value)}" for name, value in attrs],
                    f"{padding}/>",
                ]
            )
        return f"{padding}<{element.tag}{inline_attrs(attrs)}/>"

    if element.tag == "script":
        return f"{padding}<script><![CDATA[{text or ''}]]></script>"

    start = serialized_start_tag(element.tag, attrs, padding)
    end = f"{padding}</{element.tag}>"
    child_lines = [serialize_wml(child, indent + 1) for child in children]
    return "\n".join([start, *child_lines, end])


def serialized_start_tag(
    tag: str,
    attrs: list[tuple[str, str]],
    padding: str,
) -> str:
    if not use_multiline_attributes(attrs):
        return f"{padding}<{tag}{inline_attrs(attrs)}>"

    return "\n".join(
        [
            f"{padding}<{tag}",
            *[f"{padding}  {name}={quoted_xml_attr(value)}" for name, value in attrs],
            f"{padding}>",
        ]
    )


def serialized_attributes(element: etree._Element) -> list[tuple[str, str]]:
    return [(name, value) for name, value in element.attrib.items()]


def use_multiline_attributes(attrs: list[tuple[str, str]]) -> bool:
    return len(attrs) >= MULTILINE_ATTRIBUTE_COUNT


def inline_attrs(attrs: list[tuple[str, str]]) -> str:
    if not attrs:
        return ""

    return "".join(f" {name}={quoted_xml_attr(value)}" for name, value in attrs)


def quoted_xml_attr(value: str) -> str:
    return f'"{escape(value, quote=True)}"'


def extract_props(
    node: etree._Element, ignored: set[str] | None = None
) -> dict[str, Any]:
    """Extract flat child-node properties from a component node."""

    ignored = IGNORED_PROPERTIES if ignored is None else ignored
    props: dict[str, str] = {}

    for child in node:
        if child.tag not in ignored:
            props[child.tag] = (child.text or "").strip()

    return props


def extract_attributes(node: etree._Element) -> dict[str, str]:
    """Extract OpenROAD attribute rows as compact declaration strings."""

    attributes: dict[str, str] = {}
    for row in node.findall("row"):
        name = row.findtext("displayname")
        datatype = row.findtext("datatype")
        if name is not None and datatype is not None:
            attributes[name] = type_declaration(datatype, is_nullable(row))

    return attributes


def extract_methods(node: etree._Element) -> dict[str, str]:
    """Extract OpenROAD method rows as compact declaration strings."""

    methods: dict[str, str] = {}
    for row in node.findall("row"):
        name = row.findtext("displayname")
        if name is not None:
            methods[name] = method_declaration(row)

    return methods


def extract_taggedvalues(node: etree._Element) -> dict[str, str]:
    """Extract OpenROAD tagged value rows as name/value pairs."""

    taggedvalues: dict[str, str] = {}
    for row in node.findall("row"):
        name = row.findtext("name")
        if name is not None:
            taggedvalues[name] = (row.findtext("value") or "").strip()

    return taggedvalues


def first_text(node: etree._Element, *names: str) -> str:
    for name in names:
        value = node.findtext(name)
        if value is not None:
            return cast(str, value).strip()

    return ""


def type_declaration(datatype: str, nullable: bool) -> str:
    """Format an OpenROAD datatype declaration."""

    declaration = datatype.upper()
    if not nullable:
        declaration += " NOT NULL"
    return declaration


def method_declaration(row: etree._Element) -> str:
    """Format an OpenROAD method declaration."""

    parts = []
    if row.findtext("isprivate") == "1":
        parts.append("PRIVATE")

    parts.append("METHOD")

    datatype = row.findtext("datatype")
    if datatype is not None:
        parts.append("RETURNING")
        parts.append(type_declaration(datatype, is_nullable(row)))

    return " ".join(parts)


def is_nullable(row: etree._Element) -> bool:
    """Return whether an OpenROAD metadata row is nullable."""

    value = row.findtext("isnullable")
    return bool(value == "1")


def toml_props(component: Component) -> tomlkit.TOMLDocument:
    """Encode component properties as TOML front matter."""

    doc = tomlkit.document()
    props = {
        key: value
        for key, value in component.props.items()
        if key not in {"attributes", "methods", "taggedvalues", "fielddefaults"}
    }
    doc.add(component.type, tomlkit.item(props))

    for key in ["attributes", "methods", "taggedvalues", "fielddefaults"]:
        if key in component.props:
            doc.add(key, tomlkit.item(component.props[key]))

    return doc


def join_segments(segments: Sequence[str | None], separator: str) -> str:
    """Join present segments with a standalone separator."""

    return ("\n\n" + separator + "\n\n").join(
        segment.strip() for segment in segments if segment is not None
    )


def encode_w4gl(component: Component) -> str:
    """Encode a component to TOML front matter plus script body."""

    props = tomlkit.dumps(toml_props(component))
    return join_segments([props, component.script], "===")


def encode_wml(component: Component) -> str | None:
    """Return frame markup for components that have a visual definition."""

    return component.markup

"""Parse a small, intentionally conservative subset of OpenROAD XML exports."""

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from typing import Any, cast

import tomlkit
from lxml import etree

from .domain import Application, ApplicationExport, Component, IncludedApplication
from .field_defaults import parse_field_defaults_node
from .xml_text import (
    INVALID_XML,
    find_text,
    is_text_node,
    set_text,
    text_value,
    validate_instructions,
)

FRAME_COMPONENT_TYPES = frozenset({"framesource", "frametemplate"})
WML_COMPONENT_TYPES = FRAME_COMPONENT_TYPES | {"fieldtemplate"}
FIELD_TEMPLATE_CHILDREN = {"framefield", "reportfield"}
TYPED_FIELD_PROPERTIES = {"protofield", "viewfield", *FIELD_TEMPLATE_CHILDREN}

IGNORED_PROPERTIES = {
    "queries",
    "extension",
    "script",
    "fielddefaults",
    "attributes",
    "methods",
    "taggedvalues",
    "startmenu",
    "topform",
    "mainbarbottom",
    "mainbarleft",
    "mainbarright",
    "mainbartop",
}
FRAME_MARKUP_CHILDREN = {
    "startmenu",
    "topform",
    "mainbarbottom",
    "mainbarleft",
    "mainbarright",
    "mainbartop",
}
MAINBAR_MARKUP_CHILDREN = {
    "mainbarbottom",
    "mainbarleft",
    "mainbarright",
    "mainbartop",
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


def parse_w4gl(text: str, name: str) -> Component:
    """Parse Gorak .w4gl text into a component model."""

    front_matter, script = split_w4gl(text)
    metadata = tomllib.loads(front_matter)
    component_type = first_table_name(metadata)
    props = dict(metadata[component_type])
    props.pop("queries", None)
    props.update(
        {
            key: value
            for key, value in metadata.items()
            if key not in {component_type, "queries"} and isinstance(value, dict)
        }
    )

    return Component(
        name=name,
        type=component_type,
        props=props,
        script=script.strip(" \t\r\n") if script is not None else None,
    )


def split_w4gl(text: str) -> tuple[str, str | None]:
    """Split TOML front matter from optional script body."""

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip(" \t\r\n") == "===":
            return "".join(lines[:index]).strip(" \t\r\n"), "".join(
                lines[index + 1 :]
            ).strip(" \t\r\n")

    return text.strip(" \t\r\n"), None


def first_table_name(metadata: dict[str, Any]) -> str:
    for key, value in metadata.items():
        if isinstance(value, dict):
            return key

    raise ValueError(".w4gl front matter must contain a component type table")


def parse_components_xml(tree: etree._ElementTree | etree._Element) -> list[Component]:
    """Parse top-level components from an OpenROAD XML export."""

    root = xml_root(tree)
    return [parse_component_node(node) for node in root.findall("./COMPONENT")]


def parse_application_xml(
    tree: etree._ElementTree | etree._Element,
) -> ApplicationExport:
    """Parse simple application metadata and top-level components."""

    root = xml_root(tree)
    app_node = root.find("./APPLICATION")
    if app_node is None:
        raise ValueError("Missing <APPLICATION> node")

    validate_instructions(app_node)
    name = app_node.get("name")
    if name is None:
        raise ValueError("<APPLICATION> node must have a name attribute")

    from .bitmap_codec import normalized

    icon = app_node.find("windowicon")

    return ApplicationExport(
        application=Application(
            name=name,
            start_component=first_text(app_node, "proc_start", "procstart"),
            description=first_text(
                app_node, "short_remark", "versshortremarks", strip=False
            ),
            database_name=first_text(app_node, "databasename"),
            database_type=first_text(app_node, "database_type"),
            window_icon=(
                dict(icon.attrib)
                if icon is not None and "src" in icon.attrib
                else normalized(app_node.findtext("windowicon/obj_encoded") or "")
            ),
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
        app_name = (find_text(row, "appname") or "").strip(" \t\r\n")
        image = (find_text(row, "imgfilename") or "").strip(" \t\r\n")
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


def parse_component_node(
    node: etree._Element, *, project_frame: bool = True
) -> Component:
    """Parse a single OpenROAD component node."""

    validate_instructions(node)
    script_node = node.find("script")
    script = (
        text_value(script_node).strip(" \t\r\n") if script_node is not None else None
    )

    name = node.get("name")
    if name is None:
        raise ValueError("<COMPONENT> node must have a name attribute")

    component_type = node.get("{{{}}}type".format(NS["xsi"]))
    if component_type is None:
        raise ValueError("<COMPONENT> node must have an xsi:type attribute")

    if component_type in {"extlibsource", "fieldtemplate"}:
        from .field_templates import validate_component

        validate_component(node, component_type)
    props = extract_props(
        node,
        IGNORED_PROPERTIES | FIELD_TEMPLATE_CHILDREN
        if component_type == "fieldtemplate"
        else None,
    )
    from .macro_variables import read_macros

    macros = read_macros(node)
    props.pop("macro_vars", None)
    if macros:
        props["macro_vars"] = macros
    attributes_node = node.find("attributes")
    if attributes_node is not None:
        props["attributes"] = extract_attributes(attributes_node)

    methods_node = node.find("methods")
    if methods_node is not None:
        props["methods"] = extract_methods(methods_node)

    taggedvalues_node = node.find("taggedvalues")
    if taggedvalues_node is not None:
        props["taggedvalues"] = extract_taggedvalues(taggedvalues_node)

    if node.find("extension") is not None and (
        node.find("extension//*[@src]") is not None
        or (
            node.find("extension//obj_encoded") is None
            and node.find("taggedvalues/row[name='class_icons']") is not None
        )
    ):
        from .class_icons import extract_icons

        icons = extract_icons(node)
        if icons is not None:
            props["icons"] = icons

    field_defaults_node = node.find("fielddefaults")
    field_defaults: dict[str, Any] = {}
    if field_defaults_node is not None and (
        project_frame or component_type not in FRAME_COMPONENT_TYPES
    ):
        field_defaults = parse_field_defaults_node(field_defaults_node)
        props["fielddefaults"] = field_defaults

    markup_nodes = [child for child in node if child.tag in FRAME_MARKUP_CHILDREN]
    markup = (
        encode_frame_markup(markup_nodes, field_defaults)
        if project_frame and component_type in FRAME_COMPONENT_TYPES and markup_nodes
        else None
    )

    if component_type == "fieldtemplate":
        from .field_templates import encode_layout

        markup = encode_layout(node)

    from .query_metadata import encode_queries

    return Component(name, component_type, props, script, markup, encode_queries(node))


def encode_frame_markup(
    markup_nodes: list[etree._Element],
    field_defaults: dict[str, Any] | None = None,
    *,
    explicit: bool = False,
) -> str:
    """Encode an OpenROAD frame form tree as XML-compatible .wml markup."""

    index = (
        MarkupDefaultsIndex({}, {}, explicit=True)
        if explicit
        else MarkupDefaultsIndex.from_defaults(field_defaults or {})
    )
    frame = etree.Element("frame")
    for markup_node in markup_nodes:
        frame.extend(frame_markup_elements(markup_node, index))
    return serialize_wml(frame)


def frame_markup_elements(
    node: etree._Element,
    defaults_index: "MarkupDefaultsIndex",
    mapping: dict[etree._Element, etree._Element] | None = None,
) -> list[etree._Element]:
    """Keep each toolbar row as an ordered, repeated WML section."""
    if node.tag not in MAINBAR_MARKUP_CHILDREN:
        return [frame_markup_element(node, defaults_index, mapping)]
    elements = []
    for row in node.findall("row"):
        element = etree.Element(node.tag)
        if mapping is not None:
            mapping[element] = row
        copy_markup_attributes(node, element)
        copy_markup_attributes(row, element)
        append_markup_content(element, row, defaults_index, {}, mapping)
        elements.append(element)
    return elements


def frame_markup_element(
    node: etree._Element,
    defaults_index: "MarkupDefaultsIndex",
    mapping: dict[etree._Element, etree._Element] | None = None,
) -> etree._Element:
    if node.tag in MAINBAR_MARKUP_CHILDREN:
        return mainbar_markup_element(node, defaults_index, mapping)

    tag = node.get(f"{{{NS['xsi']}}}type") if node.tag == "row" else node.tag
    if not tag:
        tag = node.tag

    element = etree.Element(tag)
    if mapping is not None:
        mapping[element] = node
    copy_markup_attributes(node, element)
    if defaults_index.explicit and node.tag in TYPED_FIELD_PROPERTIES:
        native_type = node.get(f"{{{NS['xsi']}}}type")
        if native_type:
            element.set("type", native_type)
    default_properties = defaults_index.properties_for(tag, node)
    append_markup_content(element, node, defaults_index, default_properties, mapping)
    # A coordinate must remain explicit when it prevents inherited alignment,
    # even if that coordinate happens to equal the palette value.
    if (
        node.find("gravity") is None
        and "gravity" in default_properties
        and not {"xleft", "ytop"}.intersection(element.attrib)
    ):
        for coordinate in ("xleft", "ytop"):
            value = find_text(node, coordinate)
            if value is not None:
                element.set(coordinate, value.strip(" \t\r\n"))
                break
    if defaults_index.ambiguous(element):
        candidates = defaults_index.field_styles[str(tag)]
        element.set(
            "gorak_style",
            str(
                next(
                    i
                    for i, properties in enumerate(candidates, 1)
                    if properties is default_properties
                )
            ),
        )
    return element


def mainbar_markup_element(
    node: etree._Element,
    defaults_index: "MarkupDefaultsIndex",
    mapping: dict[etree._Element, etree._Element] | None = None,
) -> etree._Element:
    elements = frame_markup_elements(node, defaults_index, mapping)
    if len(elements) != 1:
        raise ValueError("Toolbar collections require frame_markup_elements")
    element = elements[0]
    if mapping is not None:
        mapping[element] = node
    return element


def append_markup_content(
    element: etree._Element,
    node: etree._Element,
    defaults_index: "MarkupDefaultsIndex",
    default_properties: dict[str, Any],
    mapping: dict[etree._Element, etree._Element] | None = None,
) -> None:
    from .field_modes import is_implicit_default

    for child in node:
        if child.tag in {"childfields", "childmenufields"}:
            append_childfields(element, child, defaults_index, mapping)
        elif child.tag == "script":
            script = etree.SubElement(element, "script")
            if mapping is not None:
                mapping[script] = child
            content = text_value(child)
            set_text(
                script,
                content if defaults_index.explicit else content.strip(" \t\r\n"),
                cdata=True,
            )
        elif is_text_node(child) and not child.attrib:
            value = text_value(child)
            if is_implicit_default(child):
                continue
            if not defaults_index.explicit:
                value = value.strip(" \t\r\n")
            if child.tag == "obj_encoded" and not defaults_index.explicit:
                # OpenROAD rewraps encoded bitmap transport across XML lines.
                # WML attributes use the XML attribute whitespace convention.
                value = (
                    value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
                )
            if should_encode_markup_attribute(child.tag, value, default_properties):
                if INVALID_XML.search(value):
                    property_node = etree.SubElement(element, child.tag)
                    set_text(property_node, value)
                    if mapping is not None:
                        mapping[property_node] = child
                else:
                    element.set(child.tag, value)
        else:
            element.append(frame_markup_element(child, defaults_index, mapping))


def append_childfields(
    parent: etree._Element,
    childfields: etree._Element,
    defaults_index: "MarkupDefaultsIndex",
    mapping: dict[etree._Element, etree._Element] | None = None,
) -> None:
    for row in childfields.findall("row"):
        parent.append(frame_markup_element(row, defaults_index, mapping))


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

    if name in {"name", "gravity"}:
        return True

    default_value = default_properties.get(name)
    return not isinstance(default_value, str) or default_value != value


@dataclass(frozen=True)
class MarkupDefaultsIndex:
    """Precomputed field-default candidates used while encoding one frame."""

    common_model_properties: dict[str, Any]
    field_styles: dict[str, list[dict[str, Any]]]
    explicit: bool = False

    @classmethod
    def from_defaults(cls, field_defaults: dict[str, Any]) -> "MarkupDefaultsIndex":
        container = field_defaults.get("common_model_container")
        common_model_properties: dict[str, Any] = {}
        if isinstance(container, dict) and isinstance(
            container.get("properties"), dict
        ):
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
            child.tag: text_value(child).strip(" \t\r\n")
            for child in node
            if isinstance(child.tag, str) and is_text_node(child)
        }
        return max(
            candidates,
            key=lambda properties: matching_default_count(properties, scalar_values),
        )

    def omitted_properties(
        self, element: etree._Element, properties: dict[str, Any]
    ) -> dict[str, str]:
        """Only scalar, omitted native values are inherited by compact WML."""
        from .xml_shapes import shape, shapes

        if not properties:
            return {}
        kind = (
            shape("framesource")["topform"]
            if element.tag == "topform"
            else str(element.tag)
        )
        fields = shape(kind)
        explicit = set(element.attrib) | {str(c.tag) for c in element}
        return {
            key: value
            for key, value in properties.items()
            if isinstance(value, str)
            and key in fields
            and fields[key] not in shapes()
            and key not in explicit
            and key != "name"
        }

    def ambiguous(self, element: etree._Element) -> bool:
        candidates = self.field_styles.get(str(element.tag), [])
        values = [self.omitted_properties(element, p) for p in candidates]
        return any(value != values[0] for value in values[1:])


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

    if is_text_node(element) and len(element):
        text_value(element)
        return "  " * indent + str(
            etree.tostring(element, encoding="unicode", with_tail=False)
        )
    if is_text_node(element) and element.tag != "script" and element.text:
        return "  " * indent + str(
            etree.tostring(element, encoding="unicode", with_tail=False)
        )
    attrs = serialized_attributes(element)
    children = list(element)
    text = cast(str | None, element.text)
    padding = "  " * indent

    if not children and not text:
        if use_multiline_attributes(attrs):
            return "\n".join(
                [
                    f"{padding}<{element.tag}",
                    *[
                        f"{padding}  {name}={quoted_xml_attr(value)}"
                        for name, value in attrs
                    ],
                    f"{padding}/>",
                ]
            )
        return f"{padding}<{element.tag}{inline_attrs(attrs)}/>"

    if element.tag == "script":
        content = (text or "").replace("]]>", "]]]]><![CDATA[>")
        content = content.replace("\r", "]]>&#13;<![CDATA[")
        return f"{padding}<script><![CDATA[{content}]]></script>"

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
    escaped = escape(value, quote=True)
    for char, reference in [("\t", "&#9;"), ("\n", "&#10;"), ("\r", "&#13;")]:
        escaped = escaped.replace(char, reference)
    return f'"{escaped}"'


def extract_props(
    node: etree._Element, ignored: set[str] | None = None
) -> dict[str, Any]:
    """Extract flat child-node properties from a component node."""

    ignored = IGNORED_PROPERTIES if ignored is None else ignored
    props: dict[str, Any] = {}

    for child in node:
        if child.tag not in ignored:
            if child.tag == "windowicon":
                from .bitmap_codec import normalized

                props["windowicon"] = (
                    dict(child.attrib)
                    if "src" in child.attrib
                    else normalized(child.findtext("obj_encoded") or "")
                )
                continue
            value = (
                text_value(child) if is_text_node(child) else child.text or ""
            ).strip(" \t\r\n")
            # Empty projections of structured designer data carry no readable
            # information. They are not part of the supported source contract.
            if not value and child.tag in {"extension", "queries"}:
                continue
            props[child.tag] = value

    return props


def extract_attributes(node: etree._Element) -> dict[str, str]:
    """Extract OpenROAD attribute rows as compact declaration strings."""

    attributes: dict[str, str] = {}
    for row in node.findall("row"):
        name = find_text(row, "displayname")
        datatype = find_text(row, "datatype")
        if name is not None and datatype is not None:
            attributes[name] = type_declaration(
                datatype,
                nullable=is_nullable(row),
                array=is_array(row),
            )
            if find_text(row, "defaultvalue") == "2":
                attributes[name] += " DEFAULT NULL"

    return attributes


def extract_methods(node: etree._Element) -> dict[str, str]:
    """Extract OpenROAD method rows as compact declaration strings."""

    methods: dict[str, str] = {}
    for row in node.findall("row"):
        name = find_text(row, "displayname")
        if name is not None:
            methods[name] = method_declaration(row)

    return methods


def extract_taggedvalues(node: etree._Element) -> dict[str, str]:
    """Extract OpenROAD tagged value rows as name/value pairs."""

    taggedvalues: dict[str, str] = {}
    for row in node.findall("row"):
        name = find_text(row, "name")
        if name is not None:
            taggedvalues[name] = (find_text(row, "value") or "").strip(" \t\r\n")

    return taggedvalues


def first_text(node: etree._Element, *names: str, strip: bool = True) -> str:
    for name in names:
        value = find_text(node, name)
        if value is not None:
            return value.strip(" \t\r\n") if strip else value

    return ""


def type_declaration(datatype: str, nullable: bool, array: bool = False) -> str:
    """Format an OpenROAD datatype declaration."""

    declaration = datatype.upper()
    if array:
        declaration = f"ARRAY OF {declaration}"
    if not nullable:
        declaration += " NOT NULL"
    return declaration


def method_declaration(row: etree._Element) -> str:
    """Format an OpenROAD method declaration."""

    parts = []
    if find_text(row, "isprivate") == "1":
        parts.append("PRIVATE")

    parts.append("METHOD")

    datatype = find_text(row, "datatype")
    if datatype is not None:
        parts.append("RETURNING")
        parts.append(
            type_declaration(
                datatype,
                nullable=is_nullable(row),
                array=is_array(row),
            )
        )

    return " ".join(parts)


def is_array(row: etree._Element) -> bool:
    """Return whether an OpenROAD metadata row is an array."""

    value = find_text(row, "isarray")
    return bool(value == "1")


def is_nullable(row: etree._Element) -> bool:
    """Return whether an OpenROAD metadata row is nullable."""

    value = find_text(row, "isnullable")
    return bool(value == "1")


def toml_props(component: Component) -> tomlkit.TOMLDocument:
    """Encode component properties as TOML front matter."""

    doc = tomlkit.document()
    props = {
        key: value
        for key, value in component.props.items()
        if key
        not in {"attributes", "methods", "taggedvalues", "fielddefaults", "icons"}
    }
    doc.add(component.type, tomlkit.item(props))

    for key in ["attributes", "methods", "taggedvalues", "fielddefaults", "icons"]:
        if key in component.props:
            doc.add(key, tomlkit.item(component.props[key]))

    return doc


def join_segments(segments: Sequence[str | None], separator: str) -> str:
    """Join present segments with a standalone separator."""

    return ("\n\n" + separator + "\n\n").join(
        segment.strip(" \t\r\n") for segment in segments if segment is not None
    )


def encode_w4gl(component: Component) -> str:
    """Encode a component to TOML front matter plus script body."""

    props = tomlkit.dumps(toml_props(component))
    return join_segments([props, component.script], "===").rstrip("\n") + "\n"


def encode_wml(component: Component) -> str | None:
    """Return frame markup for components that have a visual definition."""

    return component.markup

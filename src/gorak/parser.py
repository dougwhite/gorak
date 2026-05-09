"""Parse a small, intentionally conservative subset of OpenROAD XML exports."""

from collections.abc import Sequence
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
}

NS = {
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


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
            start_component=(app_node.findtext("proc_start") or "").strip(),
            description=(app_node.findtext("short_remark") or "").strip(),
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

    field_defaults_node = node.find("fielddefaults")
    if field_defaults_node is not None:
        props["fielddefaults"] = parse_field_defaults_node(field_defaults_node)

    topform_node = node.find("topform")
    markup = (
        encode_frame_markup_node(topform_node)
        if component_type == "framesource" and topform_node is not None
        else None
    )

    return Component(name, component_type, props, script, markup)


def encode_frame_markup_node(node: etree._Element) -> str:
    """Encode an OpenROAD frame form tree as XML-compatible .wml markup."""

    return cast(
        str,
        etree.tostring(
            frame_markup_element(node),
            encoding="unicode",
            pretty_print=True,
        ),
    ).strip()


def frame_markup_element(node: etree._Element) -> etree._Element:
    tag = node.get(f"{{{NS['xsi']}}}type") if node.tag == "row" else node.tag
    if not tag:
        tag = node.tag

    element = etree.Element(tag)
    for child in node:
        if child.tag == "childfields":
            append_childfields(element, child)
        elif child.tag == "script":
            script = etree.SubElement(element, "script")
            script.text = etree.CDATA((child.text or "").strip())
        elif len(child) == 0:
            element.set(child.tag, (child.text or "").strip())
        else:
            element.append(frame_markup_element(child))

    return element


def append_childfields(parent: etree._Element, childfields: etree._Element) -> None:
    for row in childfields.findall("row"):
        parent.append(frame_markup_element(row))


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
        if key not in {"attributes", "methods", "fielddefaults"}
    }
    doc.add(component.type, tomlkit.item(props))

    for key in ["attributes", "methods", "fielddefaults"]:
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

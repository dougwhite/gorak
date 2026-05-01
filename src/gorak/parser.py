from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import tomlkit
from lxml import etree

# Properties ignored by the flat XML property importer
IGNORED_PROPERTIES = {
    "script",
    "startmenu",
    "topform",
    "fielddefaults",
    "attributes",
    "methods",
}

# Namespace (used to get the xsi:type attribute)
NS = {
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


@dataclass
class Component:
    """Represents an OpenROAD source component (frame, userclass, etc.)"""

    name: str
    type: str
    props: dict[str, Any]
    script: str | None = None


def parse_xml(tree: etree._ElementTree | etree._Element) -> Component:
    """Parses an OpenROAD export xml into a `Component` object"""

    # First locate the root <COMPONENT> node
    node = tree.find(".//COMPONENT")
    if node is None:
        raise ValueError("Missing <COMPONENT> node")

    # Extract the script if it exists
    script_node = node.find("script")
    script = (script_node.text or "").strip() if script_node is not None else None

    # Get the component name
    name = node.get("name")
    if name is None:
        raise ValueError("<COMPONENT> node must have a name attribute")

    # Get the component type (namespaced attribute e.g xsi:type="framesource")
    type = node.get("{{{}}}type".format(NS["xsi"]))
    if type is None:
        raise ValueError("<COMPONENT> node must have an xsi:type attribute")

    # Get the component props
    props = extract_props(node)
    attributes_node = node.find("attributes")
    if attributes_node is not None:
        props["attributes"] = extract_attributes(attributes_node)

    methods_node = node.find("methods")
    if methods_node is not None:
        props["methods"] = extract_methods(methods_node)

    # Return the complete Component object
    return Component(name, type, props, script)


def extract_props(
    node: etree._Element, ignored: set[str] = IGNORED_PROPERTIES
) -> dict[str, Any]:
    """Extracts properties from a component node, except for certain ignored complex cases"""

    # Setup the props dictionary
    props: dict[str, str] = {}

    # Loop through each child property and add it to the props
    # (unless it's on the ignore list)
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
    """Encodes a component's properties into a toml document
    using the component type as a section header.

    e.g
    [framesource]
    foo = bar
    """

    doc = tomlkit.document()
    props = {
        key: value
        for key, value in component.props.items()
        if key not in {"attributes", "methods"}
    }
    doc.add(component.type, tomlkit.item(props))

    for key in ["attributes", "methods"]:
        if key in component.props:
            doc.add(key, tomlkit.item(component.props[key]))

    return doc


def join_segments(segments: Sequence[str | None], separator: str) -> str:
    """Joins multiple script segments together with the chosen separator,
    ensuring that each separator is on its own line and sandwiched between blank lines.

    Removes any None segments, and trims whitespace from each segment.

    Used to join code body segments to toml frontmatter in a reliable and clean fashion.

    Example:

    ```
    join_segments(["foo", "bar"], "===")
    ```

    Output:

    ```
    foo

    ===

    bar
    ```"""

    # Join the entries, removing any nulls
    return ("\n\n" + separator + "\n\n").join(
        segment.strip() for segment in segments if segment is not None
    )


def encode_w4gl(component: Component) -> str:
    """Encodes a Component to segmented .w4gl format,
    with toml frontmatter props prepended of the main code body

    Example file format:
    ```
    [framesource]
    datatype = "integer"

    ===

    initialize() =
    {
        CurFrame.Trace(text = 'Hello World!');
    }
    ```"""
    props = tomlkit.dumps(toml_props(component))
    return join_segments([props, component.script], "===")

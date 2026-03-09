from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from lxml import etree

# Properties ignored by the xml importer
IGNORED_PROPERTIES = {"script", "startmenu", "topform", "fielddefaults"}

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

def parse_xml(tree: etree.ElementTree) -> Component:
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

    # Return the complete Component object
    return Component(name, type, props, script)

def extract_props(node: etree._Element, ignored: set[str] = IGNORED_PROPERTIES) -> dict[str, Any]:
    """Extracts properties from a component node, except for certain ignored complex cases"""
    
    # Setup the props dictionary
    props: dict[str, str] = {}

    # Loop through each child property and add it to the props 
    # (unless it's on the ignore list)
    for child in node:
        if child.tag not in ignored:
            props[child.tag] = (child.text or "").strip()

    return props

def toml_props(component: Component) -> tomlkit.TOMLDocument:
    """Encodes a component's properties into a toml document
       using the component type as a section header.

       e.g  
       [framesource]  
       foo = bar
       """

    doc = tomlkit.document()
    doc.add(component.type, tomlkit.item(component.props))

    return doc

def join_segments(segments: list[str | None], separator: str) -> str:
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
        segment.strip() 
        for segment in segments 
        if segment is not None
    )

def write_script(component: Component, output_path: Path) -> None:
    """Writes a component's script to the specified output file. Encoded in UTF-8"""

    output_path.write_text(component.script, encoding="utf-8") # type: ignore

def get_base_path(application: str, component_name: str, project_root: Path | str) -> Path:
    """Returns the correct base filename for a given application and component, 
       relative to `project_root`"""
    root = Path(project_root)
    return root / application / component_name
from pathlib import Path
from lxml import etree
from typing import Any

class Component:
    """Represents an OpenROAD source component (frame, userclass, etc.)"""

    def __init__(self, script: str, props: dict[str, Any]) -> None:
        self.script = script
        self.props = props

# Namespace (used to get the xsi:type attribute)
NS = {
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

def load_component(xml_path: Path) -> Component:
    """Loads a component from an OpenROAD XML export"""

    # Load the xml file from disk
    tree = etree.parse(str(xml_path))

    # Extract the script
    script_node = tree.find(".//script")
    script = (script_node.text or "").strip() if script_node is not None else ""

    # Extract the props
    component_node = tree.find(".//COMPONENT")
    props = extract_props(component_node)

    return Component(script, props)

IGNORED_PROPERTIES = {"script", "startmenu", "topform", "fielddefaults"}

def extract_props(node: etree._Element) -> dict[str, Any]:
    """Extracts properties from a component node, except for certain ignored complex cases"""
    
    # Setup the props dictionary
    props: dict[str, Any] = {}

    # The ignored props list
    ignored = {"script", "startmenu", "topform", "fielddefaults"}

    # Extract the meta props first
    if node is not None:
        props["name"] = node.get("name")
        props["type"] = node.get("{%s}type" % NS["xsi"])

    # Loop through each child property and add it
    for child in node:
        if child.tag not in ignored:
            props[child.tag] = (child.text or "").strip()

    return props

def write_script(component: Component, output_path: Path) -> None:
    """Writes a component's script to the specified output file. Encoded in UTF-8"""

    output_path.write_text(component.script, encoding="utf-8")
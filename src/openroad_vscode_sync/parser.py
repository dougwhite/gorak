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
    props: dict[str, Any] = {}
    if component_node is not None:
        props["name"] = component_node.get("name")
        props["type"] = component_node.get("{%s}type" % NS["xsi"])
        props["datatype"] = component_node.findtext("datatype")

    return Component(script, props)
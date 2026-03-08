import tomlkit
from pathlib import Path
from lxml import etree
from typing import Any, Dict
from dataclasses import dataclass

@dataclass
class Component:
    """Represents an OpenROAD source component (frame, userclass, etc.)"""
    name: str
    type: str
    props: Dict[str, str]
    script: str

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

    # Find the root component node
    node = tree.find(".//COMPONENT")

    # If the node was found, extract the properties we want
    if node is not None:
        name = node.get("name")
        type = node.get("{%s}type" % NS["xsi"])
        props = extract_props(node)

    return Component(name, type, props, script)

IGNORED_PROPERTIES = {"script", "startmenu", "topform", "fielddefaults"}

def extract_props(node: etree._Element) -> dict[str, Any]:
    """Extracts properties from a component node, except for certain ignored complex cases"""
    
    # Setup the props dictionary
    props: dict[str, Any] = {}

    # Loop through each child property and add it to the props
    for child in node:
        if child.tag not in IGNORED_PROPERTIES:
            props[child.tag] = (child.text or "").strip()

    return props

def write_script(component: Component, output_path: Path) -> None:
    """Writes a component's script to the specified output file. Encoded in UTF-8"""

    output_path.write_text(component.script, encoding="utf-8")

def write_props(component: Component, output_path: Path) -> None:
    """Writes a component's props to the specified output file, in toml format"""

    doc = tomlkit.document()
    for key, value in sorted(component.props.items()):
        doc.add(key, value)

    output_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

def get_base_path(application: str, component_name: str, project_root: Path | str) -> Path:
    """Returns the correct base filename for a given application and component, 
       relative to `project_root`"""
    root = Path(project_root)
    return root / application / component_name
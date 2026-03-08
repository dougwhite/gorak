import tomlkit
from pathlib import Path
from lxml import etree
from typing import Any, Dict
from dataclasses import dataclass

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
    props: Dict[str, str]
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
    type = node.get("{%s}type" % NS["xsi"])
    if type is None:
        raise ValueError("<COMPONENT> node must have an xsi:type attribute")
    
    # Get the component props
    props = extract_props(node)

    # Return the complete Component object
    return Component(name, type, props, script)

def extract_props(node: etree._Element, ignored: set[str] = IGNORED_PROPERTIES) -> dict[str, str]:
    """Extracts properties from a component node, except for certain ignored complex cases"""
    
    # Setup the props dictionary
    props: dict[str, str] = {}

    # Loop through each child property and add it to the props 
    # (unless it's on the ignore list)
    for child in node:
        if child.tag not in ignored:
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
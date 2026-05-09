"""Report OpenROAD XML export nodes not currently represented by Gorak files."""

from typing import Any

from lxml import etree

from .parser import NS, xml_root

REPRESENTED_APP_CHILDREN = {
    "included_apps",
    "proc_start",
    "short_remark",
}
REPRESENTED_COMPONENT_CHILDREN = {
    "attributes",
    "fielddefaults",
    "methods",
    "script",
}
REPRESENTED_FRAME_CHILDREN = {
    "startmenu",
    "topform",
}


def audit_xml_file(path: str) -> dict[str, Any]:
    """Audit one OpenROAD XML export file by path."""

    return audit_xml(etree.parse(path))


def audit_xml(tree: etree._ElementTree | etree._Element) -> dict[str, Any]:
    """Return unsupported XML paths in a simple JSON-compatible shape."""

    root = xml_root(tree)
    app_node = root.find("./APPLICATION")
    components = root.findall("./COMPONENT")

    return {
        "application": audit_application_node(app_node) if app_node is not None else None,
        "components": [audit_component_node(component) for component in components],
    }


def audit_application_node(node: etree._Element) -> dict[str, Any]:
    name = node.get("name", "")
    return {
        "name": name,
        "missing_paths": [
            f"APPLICATION[{name}]/{child.tag}"
            for child in node
            if child.tag not in REPRESENTED_APP_CHILDREN
        ],
    }


def audit_component_node(node: etree._Element) -> dict[str, Any]:
    name = node.get("name", "")
    component_type = node.get(f"{{{NS['xsi']}}}type", "")
    represented_children = set(REPRESENTED_COMPONENT_CHILDREN)
    if component_type == "framesource":
        represented_children.update(REPRESENTED_FRAME_CHILDREN)

    return {
        "name": name,
        "type": component_type,
        "missing_paths": [
            f"COMPONENT[{name}]/{child.tag}"
            for child in node
            if not is_represented_component_child(child, represented_children)
        ],
    }


def is_represented_component_child(
    child: etree._Element,
    represented_children: set[str],
) -> bool:
    if child.tag in represented_children:
        return True

    return len(child) == 0

"""Ordered native macro definitions stored in component TOML metadata."""

from lxml import etree

from .errors import ProjectError
from .xml_text import is_text_node, set_text, text_value

FIELDS = ("name", "value", "shortremark")


def read_macros(component: etree._Element) -> list[dict[str, str]]:
    containers = component.findall("macro_vars")
    if not containers:
        return []
    if len(containers) != 1:
        raise ProjectError("Duplicate macro_vars collections")
    container = containers[0]
    if container.attrib or (container.text or "").strip():
        raise ProjectError("Unsupported macro_vars collection")
    rows: list[dict[str, str]] = []
    markers = 0
    for child in container:
        if (child.tail or "").strip():
            raise ProjectError("Unexpected text in macro_vars")
        if child.tag == "row_class":
            markers += 1
            if (
                markers > 1
                or child.attrib
                or len(child)
                or child.text != "macrovariable"
            ):
                raise ProjectError("Unsupported macro_vars row_class")
            continue
        if child.tag != "row" or child.attrib or (child.text or "").strip():
            raise ProjectError("Unsupported macro_vars row")
        row: dict[str, str] = {}
        for prop in child:
            key = str(prop.tag)
            if (
                key not in FIELDS
                or key in row
                or prop.attrib
                or not is_text_node(prop)
                or (prop.tail or "").strip()
            ):
                raise ProjectError(f"Unsupported macro_vars property: {key}")
            row[key] = text_value(prop)
        rows.append(row)
    return rows


def write_macros(component: etree._Element, value: object) -> None:
    # Older exports spelled even populated collections as "". Never let that
    # lossy spelling erase native definitions during a cached overlay.
    if value == "" and read_macros(component):
        raise ProjectError("Re-export component to recover macro_vars definitions")
    if value is None or value == "":
        value = []
    if not isinstance(value, list):
        raise ProjectError("macro_vars must be an array of tables")
    container = etree.Element("macro_vars")
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) - set(FIELDS)
            or any(not isinstance(v, str) for v in item.values())
        ):
            raise ProjectError("Invalid macro_vars definition")
        row = etree.SubElement(container, "row")
        for key in FIELDS:
            if key in item:
                set_text(etree.SubElement(row, key), item[key], cdata=True)
    if value:
        etree.SubElement(container, "row_class").text = "macrovariable"
    for previous in component.findall("macro_vars"):
        component.remove(previous)
    # OpenROAD removes empty collections on import; export the same form.
    if value:
        component.append(container)


def ensure_script_owner(component: etree._Element) -> None:
    """Native import only attaches macros when the script owner is present."""
    if (
        component.find("macro_vars/row") is not None
        and component.find("script") is None
    ):
        from .xml_shapes import node_kind, order_children

        set_text(etree.SubElement(component, "script"), "", cdata=True)
        order_children(component, node_kind(component, ""))

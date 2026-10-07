"""Apply readable component metadata and script edits over complete source XML."""

import re
import tomllib
from pathlib import Path

from lxml import etree

from .component_defaults import defaults_path
from .errors import ProjectError
from .parser import (
    FRAME_COMPONENT_TYPES,
    encode_w4gl,
    parse_component_node,
    parse_w4gl,
    split_w4gl,
)
from .xml_shapes import order_children, set_scalar, shape, shapes
from .xml_text import find_text, set_text, text_value

SUPPORTED_TYPES = {
    "extlibsource",
    "fieldtemplate",
    "classsource",
    "proc4glsource",
    "globsource",
    "proc3glsource",
    "scriptsource",
    "ghostsource",
    *FRAME_COMPONENT_TYPES,
    "constsource",
}


def validate_attribute_name(value: str) -> None:
    """Attribute names are XML metadata, not component paths or command arguments."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]{0,31}", value):
        raise ProjectError(f"Invalid OpenROAD attribute name: {value!r}")


def overlay_metadata(node: etree._Element, path: Path) -> None:
    from .importer import validate_name
    from .member_declarations import write_member

    if (
        node.get("{http://www.w3.org/2001/XMLSchema-instance}type")
        not in FRAME_COMPONENT_TYPES
        and defaults_path(path).exists()
    ):
        raise ProjectError("Only frames support editable component field-default files")
    original = parse_component_node(node)
    source = path.read_text()
    edited = parse_w4gl(source, path.stem)
    before = tomllib.loads(split_w4gl(encode_w4gl(original))[0])
    after = tomllib.loads(split_w4gl(source)[0])
    after.pop("queries", None)
    after.get(original.type, {}).pop("queries", None)
    from .query_metadata import overlay_queries

    overlay_queries(node, path)
    kind = original.type
    if edited.type != kind:
        raise ProjectError("Changing component type is not supported")
    if kind not in SUPPORTED_TYPES:
        if before != after or original.script != edited.script:
            raise ProjectError(f"Editing component type is not supported: {kind}")
        return
    if set(after) - {
        kind,
        "attributes",
        "methods",
        "taggedvalues",
        "fielddefaults",
        "icons",
    }:
        raise ProjectError("Unsupported component front matter")
    if kind not in FRAME_COMPONENT_TYPES and after.get("fielddefaults") != before.get(
        "fielddefaults"
    ):
        raise ProjectError(f"{kind} does not support editable field defaults")
    for key in set(before[kind]) | set(after[kind]):
        old, new = before[kind].get(key), after[kind].get(key)
        if key == "macro_vars" and shape(kind).get(key) == "macrovariable_ARRAY":
            from .macro_variables import write_macros

            write_macros(node, new)
            order_children(node, kind)
            continue
        if old == new:
            continue
        # Compact projections spell empty object/array properties as "".
        # OpenROAD removes empty containers on import; these spellings agree.
        if new == "" and old is None and shape(kind).get(key) in shapes():
            continue
        if key == "windowicon" and isinstance(new, (str, dict)) and new:
            from .image_assets import encode_icon

            for old_icon in node.findall("windowicon"):
                node.remove(old_icon)
            etree.SubElement(
                etree.SubElement(node, "windowicon"), "obj_encoded"
            ).text = encode_icon(path.parent, new)
            continue
        if new is not None and not isinstance(new, (str, int, bool)):
            raise ProjectError(f"Component property must be scalar: {key}")
        set_scalar(
            node,
            kind,
            key,
            None
            if new is None
            else str(int(new))
            if isinstance(new, bool)
            else str(new),
        )
    for table, row_kind, identifier in [
        ("attributes", "attributeobject", "displayname"),
        ("methods", "methodobject", "displayname"),
        ("taggedvalues", "taggedvalue", "name"),
    ]:
        if before.get(table, {}) == after.get(table, {}):
            continue
        if table not in shape(kind):
            raise ProjectError(f"{kind} does not support {table}")
        declarations = after.get(table, {})
        if not isinstance(declarations, dict):
            raise ProjectError(f"Invalid {table} declarations")
        container = node.find(table)
        if container is None:
            container = etree.SubElement(node, table)
            etree.SubElement(container, "row_class").text = row_kind
        rows: dict[str, etree._Element] = {}
        for row in container.findall("row"):
            name = find_text(row, identifier)
            if name is None or name.casefold() in rows:
                raise ProjectError(f"Ambiguous {table} row identity")
            rows[name.casefold()] = row
        seen: set[str] = set()
        for name, declaration in declarations.items():
            if table == "taggedvalues" and not isinstance(declaration, str):
                raise ProjectError(f"Invalid declaration for {name}")
            if name.casefold() in seen:
                raise ProjectError(f"Duplicate declaration: {name}")
            seen.add(name.casefold())
            if table == "attributes":
                validate_attribute_name(name)
            elif table == "methods":
                validate_name(name)
            row = rows.get(name.casefold())
            if row is None:
                row = etree.SubElement(container, "row")
                set_text(etree.SubElement(row, identifier), name)
            if find_text(row, identifier) != name:
                set_scalar(row, row_kind, identifier, name)
            if before.get(table, {}).get(name) == declaration:
                continue
            if table == "taggedvalues":
                set_scalar(row, row_kind, "value", declaration)
                continue
            write_member(row, declaration, table)
        for key, row in rows.items():
            if key not in seen:
                container.remove(row)
        order_children(container, shape(kind)[table])
        order_children(node, kind)
    if original.script != edited.script:
        script = node.find("script")
        previous = text_value(script)
        leading = previous[: len(previous) - len(previous.lstrip(" \t\r\n"))]
        trailing = previous[len(previous.rstrip(" \t\r\n")) :]
        set_scalar(
            node,
            kind,
            "script",
            None if edited.script is None else leading + edited.script + trailing,
        )

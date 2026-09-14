"""Apply readable component metadata and script edits over complete source XML."""

import re
import tomllib
from pathlib import Path

from lxml import etree

from .errors import ProjectError
from .parser import encode_w4gl, parse_component_node, parse_w4gl, split_w4gl
from .xml_shapes import order_children, set_scalar, shape

SUPPORTED_TYPES = {
    "classsource",
    "proc4glsource",
    "globsource",
    "proc3glsource",
    "scriptsource",
    "ghostsource",
    "framesource",
    "constsource",
}


def overlay_metadata(node: etree._Element, path: Path) -> None:
    from .importer import validate_name
    from .xml_writer import datatype

    original = parse_component_node(node)
    source = path.read_text()
    edited = parse_w4gl(source, path.stem)
    before = tomllib.loads(split_w4gl(encode_w4gl(original))[0])
    after = tomllib.loads(split_w4gl(source)[0])
    kind = original.type
    if edited.type != kind:
        raise ProjectError("Changing component type is not supported")
    if kind not in SUPPORTED_TYPES:
        if before != after or original.script != edited.script:
            raise ProjectError(f"Editing component type is not supported: {kind}")
        return
    if set(after) - {kind, "attributes", "methods", "taggedvalues", "fielddefaults"}:
        raise ProjectError("Unsupported component front matter")
    if kind != "framesource" and after.get("fielddefaults") != before.get(
        "fielddefaults"
    ):
        raise ProjectError(f"{kind} does not support editable field defaults")
    for key in set(before[kind]) | set(after[kind]):
        old, new = before[kind].get(key), after[kind].get(key)
        if old == new:
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
            name = row.findtext(identifier)
            if name is None or name.casefold() in rows:
                raise ProjectError(f"Ambiguous {table} row identity")
            rows[name.casefold()] = row
        seen: set[str] = set()
        for name, declaration in declarations.items():
            if not isinstance(declaration, str):
                raise ProjectError(f"Invalid declaration for {name}")
            if name.casefold() in seen:
                raise ProjectError(f"Duplicate declaration: {name}")
            seen.add(name.casefold())
            if table != "taggedvalues":
                validate_name(name)
            row = rows.get(name.casefold())
            if row is None:
                row = etree.SubElement(container, "row")
                etree.SubElement(row, identifier).text = name
            if row.findtext(identifier) != name:
                set_scalar(row, row_kind, identifier, name)
            if before.get(table, {}).get(name) == declaration:
                continue
            if table == "taggedvalues":
                set_scalar(row, row_kind, "value", declaration)
                continue
            managed = ["datatype", "isarray", "isnullable"]
            if table == "methods":
                managed.append("isprivate")
            for key in managed:
                for child in row.findall(key):
                    row.remove(child)
            if table == "methods":
                match = re.fullmatch(
                    r"(PRIVATE )?METHOD(?: RETURNING (.+))?", declaration
                )
                if not match:
                    raise ProjectError(f"Invalid method declaration: {declaration}")
                if match[1]:
                    etree.SubElement(row, "isprivate").text = "1"
                declaration = match[2] or ""
            if declaration:
                datatype(row, declaration)
            order_children(row, row_kind)
        for key, row in rows.items():
            if key not in seen:
                container.remove(row)
        order_children(container, shape(kind)[table])
        order_children(node, kind)
    if original.script != edited.script:
        script = node.find("script")
        previous = script.text or "" if script is not None else ""
        leading = previous[: len(previous) - len(previous.lstrip())]
        trailing = previous[len(previous.rstrip()) :]
        set_scalar(
            node,
            kind,
            "script",
            None if edited.script is None else leading + edited.script + trailing,
        )

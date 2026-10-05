"""Readable saved-query objects with native XML reconstruction."""

from typing import Any

from lxml import etree

from .errors import ProjectError
from .xml_shapes import shape
from .xml_text import is_text_node, set_text, text_value

XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"
# Explicit mapping prevents unknown native properties being silently discarded.
FIELDS = {
    "queryobject": {
        "name": "name",
        "columns": "columns",
        "target_prefix": "targetprefix",
        "tables": "tables",
        "where": "designtimewhere",
        "runtime_where": "runtimewhere",
        "dynamic_where": "dynqualwhere",
        "having": "havingclause",
        "distinct": "isdistinct",
        "lookup_frame": "lookupframe",
        "lookup_has_qualify": "lookuphasqualify",
        "lookup_initial_qualify": "lookupinitialqualify",
        "query": "query",
        "query_name": "queryname",
        "delete_rule": "deleterule",
        "join_field_updateable": "joinfieldisupdateable",
        "primary_key_updateable": "primkeyisupdateable",
    },
    "querycol": {
        "name": "columnname",
        "alias": "asname",
        "table": "fromtable_idx",
        "expression": "expression",
        "targets": "targets",
        "group_by": "groupby",
        "order_by": "orderby",
        "qualify_title": "qualtitle",
        "qualify_type": "qualtype",
        "is_expression": "isexpression",
        "locked": "islock",
        "primary_key": "isprimkey",
        "sequenced": "issequenced",
        "lookup_visible": "lookupvisible",
    },
    "queryparm": {
        "expression": "expression",
        "result_assignment": "resultassignment",
        "db_handle_field": "isdbhandlefield",
        "delete_where": "isdeletewhere",
        "file_handle_field": "isfilehandlefield",
        "insert_target": "isinserttarget",
        "select_target": "isselecttarget",
        "update_target": "isupdatetarget",
        "update_where": "isupdatewhere",
        "use_prefix": "useprefix",
    },
    "querytable": {
        "name": "tablename",
        "alias": "corrname",
        "owner": "ownername",
        "use": "tableuse",
    },
}
DATATYPE = {
    "code": "datatypecode",
    "length": "datatypelength",
    "nullable": "datatypenullable",
    "precision": "datatypeprecision",
}
ARRAYS = {"columns": "querycol", "targets": "queryparm", "tables": "querytable"}


def element_only(node: etree._Element) -> None:
    if (node.text or "").strip() or any((c.tail or "").strip() for c in node):
        raise ProjectError("Mixed query content is unsupported")


def encode_scalar(node: etree._Element, datatype: str) -> Any:
    if node.attrib or not is_text_node(node):
        raise ProjectError(f"Unsupported query scalar: {node.tag}")
    value = text_value(node)
    if datatype == "or_bool":
        if value not in {"", "0", "1"}:
            raise ProjectError(f"Invalid query boolean: {node.tag}")
        return None if value == "" else value == "1"
    if datatype in {"xs:integer", "xs:nonNegativeInteger"}:
        if value == "":
            return None
        try:
            number = int(value)
        except ValueError as ex:
            raise ProjectError(f"Invalid query integer: {node.tag}") from ex
        if str(number) != value or (datatype == "xs:nonNegativeInteger" and number < 0):
            raise ProjectError(f"Noncanonical query integer: {node.tag}")
        return number
    return value


def decode_scalar(tag: str, value: Any, datatype: str) -> etree._Element:
    node = etree.Element(tag)
    if datatype == "or_bool":
        if value is not None and type(value) is not bool:
            raise ProjectError(f"Expected query boolean: {tag}")
        text = "" if value is None else str(int(value))
    elif datatype in {"xs:integer", "xs:nonNegativeInteger"}:
        if value is not None and (
            type(value) is not int
            or (datatype == "xs:nonNegativeInteger" and value < 0)
        ):
            raise ProjectError(f"Expected query integer: {tag}")
        text = "" if value is None else str(value)
    else:
        if not isinstance(value, str):
            raise ProjectError(f"Expected query text: {tag}")
        text = value
    set_text(node, text)
    return node


def encode_collection(node: etree._Element, kind: str) -> list[dict[str, Any]]:
    element_only(node)
    if node.attrib:
        raise ProjectError("Query collection attributes are unsupported")
    rows = node.findall("row")
    expected = ["row"] * len(rows) + (["row_class"] if rows else [])
    if [c.tag for c in node] != expected or (
        rows and (node[-1].attrib or len(node[-1]) or node[-1].text != kind)
    ):
        raise ProjectError(f"Unsupported {kind} collection shape")
    return [encode_object(row, kind) for row in rows]


def encode_object(node: etree._Element, kind: str) -> dict[str, Any]:
    element_only(node)
    if set(node.attrib) - {XSI} or (XSI in node.attrib and node.get(XSI) != kind):
        raise ProjectError(f"Unsupported query object type or attributes: {kind}")
    fields = dict(FIELDS[kind])
    if kind == "querycol":
        fields.update(DATATYPE)
    reverse = {native: key for key, native in fields.items()}
    values: dict[str, Any] = {}
    for child in node:
        if child.tag not in reverse or child.tag in values:
            raise ProjectError(f"Unsupported or duplicate query property: {child.tag}")
        values[child.tag] = (
            encode_collection(child, ARRAYS[child.tag])
            if child.tag in ARRAYS
            else encode_scalar(child, shape(kind)[child.tag])
        )
    result = {
        key: values[native] for key, native in FIELDS[kind].items() if native in values
    }
    if kind == "querycol":
        types = {
            key: values[native] for key, native in DATATYPE.items() if native in values
        }
        if types:
            result["datatype"] = types
    if XSI in node.attrib:
        result["type"] = kind
    return result


def decode_collection(tag: str, value: Any, kind: str) -> etree._Element:
    if not isinstance(value, list):
        raise ProjectError(f"Expected an array for {tag}; re-export the component")
    node = etree.Element(tag)
    node.extend(decode_object(item, kind) for item in value)
    if value:
        etree.SubElement(node, "row_class").text = kind
    return node


def decode_object(value: Any, kind: str) -> etree._Element:
    if not isinstance(value, dict):
        raise ProjectError(f"Expected query object: {kind}")
    allowed = (
        set(FIELDS[kind]) | {"type"} | ({"datatype"} if kind == "querycol" else set())
    )
    if set(value) - allowed or ("type" in value and value["type"] != kind):
        raise ProjectError(f"Unsupported properties or type for {kind}")
    native = {
        FIELDS[kind][key]: item for key, item in value.items() if key in FIELDS[kind]
    }
    if "datatype" in value:
        types = value["datatype"]
        if not isinstance(types, dict) or not types or set(types) - set(DATATYPE):
            raise ProjectError("Invalid query column datatype")
        native.update({DATATYPE[key]: item for key, item in types.items()})
    node = etree.Element("row")
    if "type" in value:
        node.set(XSI, kind)
    for tag, datatype in shape(kind).items():
        if tag in native:
            node.append(
                decode_collection(tag, native[tag], ARRAYS[tag])
                if tag in ARRAYS
                else decode_scalar(tag, native[tag], datatype)
            )
    return node

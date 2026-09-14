"""Complete readable source, independent of export caches and XML companions.

Scripts live only in W4GL bodies or WML event elements. Named TOML/JSON metadata
holds the remaining native properties, including metadata on array containers.
"""

import tomllib
from pathlib import Path
from typing import Any

import tomlkit
from lxml import etree

from .errors import ProjectError
from .parser import FRAME_MARKUP_CHILDREN, NS, split_w4gl
from .readable_markup import decode_markup, encode_markup
from .readable_values import XSI, decode_value, encode_properties, encode_value
from .xml_shapes import order_children, shape

COMPONENT_TYPES = {
    "classsource",
    "proc4glsource",
    "globsource",
    "proc3glsource",
    "scriptsource",
    "ghostsource",
    "framesource",
    "constsource",
}
APP_FIELDS = {
    "description": ("versshortremarks", "xs:string"),
    "extension": ("extension", "object_ARRAY"),
    "taggedvalues": ("taggedvalues", "taggedvalue_ARRAY"),
    "included_applications": ("included_apps", "inclapp_ARRAY"),
    "starting_component": ("procstart", "or_idname"),
    "database_name": ("databasename", "xs:string"),
    "database_type": ("database_type", "xs:string"),
    "commandline": ("commandline", "xs:string"),
    "windowicon": ("windowicon", "bitmapobject"),
    "globalsfile": ("globalsfile", "xs:string"),
    "appflags": ("appflags", "xs:integer"),
}


def metadata(path: Path) -> dict[str, Any]:
    return tomllib.loads(split_w4gl(path.read_bytes().decode("utf-8"))[0])


def is_complete(path: Path) -> bool:
    return metadata(path).get("source_format") == 2


def encode_component(
    node: etree._Element, *, defaults: dict[str, Any] | None = None
) -> tuple[str, str | None]:
    kind = node.get(XSI, "")
    if kind not in COMPONENT_TYPES:
        raise ProjectError(f"Unsupported component type: {kind}")
    if (node.text or "").strip():
        raise ProjectError("Unexpected component text")
    props = encode_properties(node, kind, {"script", *FRAME_MARKUP_CHILDREN})
    doc: dict[str, Any] = {"source_format": 2}
    overrides = None
    if defaults is not None and node.find("fielddefaults") is not None:
        from .palette import difference, encode

        overrides = difference(defaults, encode(node.find("fielddefaults")))
        props.pop("fielddefaults", None)
        doc["defaults_inherited"] = True
    script = node.find("script")
    body = None
    if script is not None:
        if script.attrib or len(script):
            raise ProjectError("Structured component script is unsupported")
        text = script.text or ""
        body = text.strip()
        prefix = text[: len(text) - len(text.lstrip())]
        suffix = text[len(text.rstrip()) :] if body else ""
        if prefix:
            doc["script_prefix"] = prefix
        if suffix:
            doc["script_suffix"] = suffix
    # The component table must precede other tables for legacy model readers.
    doc[kind] = props
    if overrides:
        doc["fielddefaults"] = overrides
    attributes = {k: v for k, v in node.attrib.items() if k not in {XSI, "name"}}
    if attributes:
        doc["component_attributes"] = attributes
    text = tomlkit.dumps(doc).rstrip() + "\n"
    if body is not None:
        text += "\n===\n" + body + "\n"
    markup = encode_markup(node) if kind == "framesource" else None
    from .importer import signature

    if signature(
        decode_component_text(
            str(node.get("name", "")), text, markup, defaults=defaults
        )
    ) != signature(node):
        raise ProjectError(
            "Component cannot be represented losslessly as readable source"
        )
    return text, markup


def decode_component(path: Path) -> etree._Element:
    text = path.read_bytes().decode("utf-8")
    values = tomllib.loads(split_w4gl(text)[0])
    markup = (
        path.with_suffix(".wml").read_bytes().decode("utf-8")
        if "framesource" in values
        else None
    )
    from .palette import parent_defaults

    return decode_component_text(
        path.stem, text, markup, defaults=parent_defaults(path.parent)
    )


def decode_component_text(
    name: str, text: str, markup: str | None, *, defaults: dict[str, Any] | None = None
) -> etree._Element:
    from .importer import validate_name

    validate_name(name)
    front, script = split_w4gl(text)
    values = tomllib.loads(front)
    kinds = COMPONENT_TYPES & values.keys()
    if values.get("source_format") != 2 or len(kinds) != 1:
        raise ProjectError("Expected one component table with source_format=2")
    kind = kinds.pop()
    if set(values) - {
        kind,
        "source_format",
        "script_prefix",
        "script_suffix",
        "component_attributes",
        "defaults_inherited",
        "fielddefaults",
    }:
        raise ProjectError("Unsupported readable source metadata")
    props = values[kind]
    if not isinstance(props, dict) or set(props) - (
        set(shape(kind)) - {"script", *FRAME_MARKUP_CHILDREN}
    ):
        raise ProjectError(
            "Scripts and layout must be authored in their readable sections"
        )
    node = decode_value("COMPONENT", props, kind)
    if "defaults_inherited" in values:
        from .palette import decode, merge

        if (
            values["defaults_inherited"] is not True
            or kind != "framesource"
            or "fielddefaults" in props
        ):
            raise ProjectError("Invalid inherited defaults declaration")
        overrides = values.get("fielddefaults", {})
        if not isinstance(overrides, dict):
            raise ProjectError("Frame defaults must be a table")
        node.append(decode(merge(defaults or {}, overrides)))
    elif "fielddefaults" in values:
        raise ProjectError("Field-default overrides require defaults_inherited=true")
    node.set("name", name)
    node.set(XSI, kind)
    attributes = values.get("component_attributes", {})
    if not isinstance(attributes, dict) or any(
        not isinstance(v, str) or k in {XSI, "name"} for k, v in attributes.items()
    ):
        raise ProjectError("Invalid component attributes")
    node.attrib.update(attributes)
    for key in ("script_prefix", "script_suffix"):
        value = values.get(key, "")
        if not isinstance(value, str) or value.strip():
            raise ProjectError(f"{key} must contain whitespace only")
        if value and script is None:
            raise ProjectError("Script whitespace requires a script body")
    if script is not None:
        if "script" not in shape(kind):
            raise ProjectError(f"{kind} does not accept a script")
        etree.SubElement(node, "script").text = etree.CDATA(
            values.get("script_prefix", "") + script + values.get("script_suffix", "")
        )
    if kind == "framesource":
        if markup is None:
            raise ProjectError("Frame requires a WML source file")
        node.extend(decode_markup(markup))
    order_children(node, kind)
    # Literal CR inside CDATA is normalized by XML parsers. Plain XML text emits
    # character references, preserving the source through transport as well.
    for event in node.iter("script"):
        if event.text and "\r" in event.text:
            event.text = str(event.text)
    return node


def encode_application(node: etree._Element) -> dict[str, Any]:
    result: dict[str, Any] = {"source_format": 2}
    lookup = {tag: (key, kind) for key, (tag, kind) in APP_FIELDS.items()}
    for child in node:
        if child.tag not in lookup or (child.tail or "").strip():
            raise ProjectError(f"Unsupported application property: {child.tag}")
        key, kind = lookup[str(child.tag)]
        if key in result:
            raise ProjectError(f"Duplicate application property: {key}")
        result[key] = encode_value(child, kind)
    attributes = {k: v for k, v in node.attrib.items() if k != "name"}
    if attributes:
        result["application_attributes"] = attributes
    if (node.text or "").strip():
        raise ProjectError("Unexpected application text")
    from .importer import signature

    if signature(
        decode_application_values(str(node.get("name", "")), result)
    ) != signature(node):
        raise ProjectError(
            "Application cannot be represented losslessly as readable source"
        )
    return result


def decode_application(folder: Path) -> etree._Element:
    from .project import read_json

    return decode_application_values(folder.name, read_json(folder / "app.json"))


def decode_application_values(name: str, values: dict[str, Any]) -> etree._Element:
    from .importer import validate_name

    validate_name(name)
    if values.get("source_format") != 2 or set(values) - {
        *APP_FIELDS,
        "source_format",
        "application_attributes",
    }:
        raise ProjectError("Unsupported application source metadata")
    node = etree.Element("APPLICATION", name=name, nsmap=NS)
    attributes = values.get("application_attributes", {})
    if not isinstance(attributes, dict) or any(
        not isinstance(v, str) or k == "name" for k, v in attributes.items()
    ):
        raise ProjectError("Invalid application attributes")
    node.attrib.update(attributes)
    for key, (tag, kind) in APP_FIELDS.items():
        if key in values:
            node.append(decode_value(tag, values[key], kind))
    return node

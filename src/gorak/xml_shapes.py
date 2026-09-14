"""Ordered XML property shapes used to preserve OpenROAD serialization order.

The data describes the OpenROAD export protocol, not database storage layouts.
Unknown properties are preserved when untouched and rejected when newly authored.
"""

import json
from functools import lru_cache
from importlib.resources import files
from typing import cast

from lxml import etree

from .errors import ProjectError
from .parser import NS


@lru_cache(maxsize=1)
def shapes() -> dict[str, dict[str, str]]:
    return cast(
        dict[str, dict[str, str]],
        json.loads(files("gorak.templates").joinpath("xml_shapes.json").read_text()),
    )


def shape(kind: str) -> dict[str, str]:
    try:
        return shapes()[kind]
    except KeyError as ex:
        raise ProjectError(f"Unsupported XML type: {kind}") from ex


def node_kind(node: etree._Element, fallback: str) -> str:
    return str(node.get(f"{{{NS['xsi']}}}type", fallback))


def set_scalar(node: etree._Element, kind: str, key: str, value: str | None) -> None:
    properties = shape(kind)
    if key not in properties or properties[key] in shapes():
        raise ProjectError(f"Unsupported scalar property: {kind}/{key}")
    matches = node.findall(key)
    if len(matches) > 1 or any(len(c) or c.attrib for c in matches):
        raise ProjectError(f"Ambiguous or structured scalar property: {kind}/{key}")
    if value is None:
        for c in matches:
            node.remove(c)
        return
    child = matches[0] if matches else etree.SubElement(node, key)
    child.text = etree.CDATA(value) if key == "script" else value
    if not matches:
        order_children(node, kind)


def order_children(node: etree._Element, kind: str) -> None:
    order = list(shape(kind))
    # Existing unknown fields must never be silently moved across known fields.
    if any(c.tag not in order for c in node):
        raise ProjectError(f"Cannot order unknown XML properties for {kind}")
    node[:] = sorted(node, key=lambda c: order.index(str(c.tag)))


@lru_cache(maxsize=1)
def bases() -> dict[str, str]:
    return cast(
        dict[str, str],
        json.loads(files("gorak.templates").joinpath("xml_bases.json").read_text()),
    )


def derives(kind: str, base: str) -> bool:
    while kind:
        if kind == base:
            return True
        kind = bases().get(kind, "")
    return False

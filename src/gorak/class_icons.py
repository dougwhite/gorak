"""Ordered class icon collections in W4GL metadata."""

import tomllib
from pathlib import Path
from typing import Any

from lxml import etree

from .errors import ProjectError
from .style_values import XSI


def collection(data: dict[str, Any], key: str) -> etree._Element:
    if (
        not isinstance(data, dict)
        or set(data) != {"entries"}
        or not isinstance(key, str)
        or not isinstance(data["entries"], list)
    ):
        raise ProjectError("Invalid class icon collection")
    extension = etree.Element("extension")
    lookup = etree.SubElement(extension, "row", {XSI: "choicelist"})
    items = etree.SubElement(lookup, "choiceitems")
    row = etree.SubElement(items, "row")
    for tag, text in [
        ("enumdisplay", key),
        ("enumtext", key),
        ("enumvalue", "2"),
    ]:
        etree.SubElement(row, tag).text = text
    etree.SubElement(items, "row_class").text = "choicedetail"
    icons = etree.SubElement(extension, "row", {XSI: "choicelist"})
    items = etree.SubElement(icons, "choiceitems")
    seen = set()
    for entry in data["entries"]:
        if (
            not isinstance(entry, dict)
            or "src" not in entry
            or "id" not in entry
            or not isinstance(entry["id"], str)
            or not isinstance(entry["src"], str)
            or entry["id"] in seen
        ):
            raise ProjectError("Invalid or duplicate class icon entry")
        seen.add(entry["id"])
        row = etree.SubElement(items, "row")
        etree.SubElement(row, "enumvalue").text = entry["id"]
        bitmap = etree.SubElement(row, "enumbitmap")
        from .image_assets import validate_reference

        bitmap.attrib.update(
            validate_reference({k: v for k, v in entry.items() if k != "id"})
        )
    etree.SubElement(items, "row_class").text = "choicedetail"
    etree.SubElement(extension, "row_class").text = "object"
    return extension


def extract_icons(node: etree._Element) -> dict[str, Any] | None:
    extension = node.find("extension")
    if extension is None or not len(extension):
        return None
    if node.get(XSI) != "classsource":
        raise ProjectError("Only classes support icons metadata")
    key = node.findtext("taggedvalues/row[name='class_icons']/value")
    try:
        data = {
            "entries": [
                {"id": row.findtext("enumvalue"), **dict(row.find("enumbitmap").attrib)}
                for row in extension.findall("row")[1].findall("choiceitems/row")
            ],
        }
        from .importer import signature

        if not isinstance(key, str) or signature(collection(data, key)) != signature(
            extension
        ):
            raise ProjectError("Unsupported class extension structure")
    except (AttributeError, IndexError, TypeError) as ex:
        raise ProjectError("Unsupported class extension structure") from ex
    return data


def overlay_icons(node: etree._Element, source: Path) -> None:
    from .parser import split_w4gl

    if source.with_suffix(".icons.json").exists():
        raise ProjectError("Obsolete class icon sidecar; re-export this component")
    metadata = tomllib.loads(split_w4gl(source.read_text())[0])
    old = node.find("extension")
    if "icons" not in metadata:
        if (
            old is not None
            and len(old)
            and node.find("taggedvalues/row[name='class_icons']") is not None
        ):
            raise ProjectError(
                "Missing class icons metadata; use [icons] entries = [] for an empty collection"
            )
        return
    if node.get(XSI) != "classsource":
        raise ProjectError("Only classes support icons metadata")
    key = node.findtext("taggedvalues/row[name='class_icons']/value")
    if key is None:
        raise ProjectError("Class icons require a class_icons tagged value")
    replacement = collection(metadata["icons"], key)
    from .image_assets import resolve

    resolve(replacement, source.parent)
    position = (
        node.index(old)
        if old is not None
        else next(
            (
                i
                for i, child in enumerate(node)
                if child.tag in {"taggedvalues", "superclass"}
            ),
            len(node),
        )
    )
    for previous in node.findall("extension"):
        node.remove(previous)
    node.insert(position, replacement)

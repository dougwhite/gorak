"""Ordered class icon collections, separate from ordinary class declarations."""

import json
from pathlib import Path
from typing import Any

from lxml import etree

from .errors import ProjectError
from .style_values import XSI


def collection(data: dict[str, Any]) -> etree._Element:
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "key", "entries"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or not isinstance(data["key"], str)
        or not isinstance(data["entries"], list)
    ):
        raise ProjectError("Invalid class icon collection")
    extension = etree.Element("extension")
    lookup = etree.SubElement(extension, "row", {XSI: "choicelist"})
    items = etree.SubElement(lookup, "choiceitems")
    row = etree.SubElement(items, "row")
    for tag, text in [
        ("enumdisplay", data["key"]),
        ("enumtext", data["key"]),
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


def write_icons(node: etree._Element, source: Path) -> None:
    path = source.with_suffix(".icons.json")
    extension = node.find("extension")
    if extension is None or not len(extension):
        path.unlink(missing_ok=True)
        return
    key = node.findtext("taggedvalues/row[name='class_icons']/value")
    try:
        data = {
            "version": 1,
            "key": key,
            "entries": [
                {"id": row.findtext("enumvalue"), **dict(row.find("enumbitmap").attrib)}
                for row in extension.findall("row")[1].findall("choiceitems/row")
            ],
        }
        from .importer import signature

        if signature(collection(data)) != signature(extension):
            raise ProjectError("Unsupported class extension structure")
    except (AttributeError, IndexError, TypeError) as ex:
        raise ProjectError("Unsupported class extension structure") from ex
    path.write_text(json.dumps(data, indent=2) + "\n")


def overlay_icons(node: etree._Element, source: Path) -> None:
    path = source.with_suffix(".icons.json")
    old = node.find("extension")
    if (
        old is not None
        and len(old)
        and not path.exists()
        and node.find("taggedvalues/row[name='class_icons']") is not None
    ):
        raise ProjectError("Missing class icon sidecar; re-export this component")
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as ex:
        raise ProjectError(f"Invalid class icon sidecar: {ex}") from ex
    replacement = collection(data)
    if node.findtext("taggedvalues/row[name='class_icons']/value") != data["key"]:
        raise ProjectError("Class icon key does not match class_icons tagged value")
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

"""Versioned, lossless saved query definitions adjacent to component source."""

import json
from pathlib import Path
from typing import Any

from lxml import etree

from .errors import ProjectError
from .query_values import decode_collection, encode_collection


def query_path(source: Path) -> Path:
    return source.with_suffix(".queries.json")


def encode_queries(node: etree._Element) -> dict[str, Any] | None:
    nodes = node.findall("queries")
    if len(nodes) > 1:
        raise ProjectError("Duplicate queries collections are unsupported")
    if not nodes:
        return None
    try:
        return {"version": 1, "queries": encode_collection(nodes[0], "queryobject")}
    except ProjectError as ex:
        raise ProjectError(f"Cannot preserve query metadata: {ex}") from ex


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectError(f"Duplicate query metadata property: {key}")
        result[key] = value
    return result


def read_queries(source: Path) -> etree._Element | None:
    path = query_path(source)
    if not path.exists():
        return None
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
        if (
            not isinstance(data, dict)
            or set(data) != {"version", "queries"}
            or type(data["version"]) is not int
            or data["version"] != 1
        ):
            raise ProjectError(
                "Expected version 1 query metadata with version and queries properties"
            )
        if data["queries"] is None:
            return None
        return decode_collection("queries", data["queries"], "queryobject")
    except (ValueError, OSError, ProjectError) as ex:
        raise ProjectError(f"Invalid query metadata {path}: {ex}") from ex


def write_queries(source: Path, value: dict[str, Any] | None) -> None:
    path = query_path(source)
    if value is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(
            json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )


def overlay_queries(node: etree._Element, source: Path) -> None:
    if node.find("queries") is not None and not query_path(source).is_file():
        raise ProjectError(
            f"Missing query metadata {query_path(source)}; re-export the component. "
            'To remove queries explicitly, use {"version": 1, "queries": null}.'
        )
    desired = read_queries(source)
    position = next((i for i, child in enumerate(node) if child.tag == "queries"), None)
    for previous in node.findall("queries"):
        node.remove(previous)
    if desired is not None:
        if position is not None:
            node.insert(position, desired)
        else:
            from .xml_shapes import shape

            fields = list(
                shape(str(node.get("{http://www.w3.org/2001/XMLSchema-instance}type")))
            )
            if "queries" not in fields:
                raise ProjectError("Component does not support queries")
            position = next(
                (
                    i
                    for i, child in enumerate(node)
                    if child.tag in fields
                    and fields.index(child.tag) > fields.index("queries")
                ),
                len(node),
            )
            node.insert(position, desired)

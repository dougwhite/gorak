"""Modal native style rows without splitting samples or changing slot identity."""

import json
from collections import Counter
from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from . import native_styles as styles
from .errors import ProjectError
from .style_values import numbered


def ordered_key(value: Any) -> str:
    """Property insertion order is native XML order, not cosmetic JSON formatting."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _mode(values: Sequence[Any], previous: Any) -> Any:
    keys = [ordered_key(value) for value in values]
    counts = Counter(keys)
    maximum = max(counts.values())
    preferred = ordered_key(previous)
    winner = (
        preferred
        if counts[preferred] == maximum
        else next(key for key in keys if counts[key] == maximum)
    )
    return deepcopy(values[keys.index(winner)])


def _shape(sheet: styles.Json) -> list[Any]:
    return [
        [key, numbered(sheet["groups"][key]["styles"], "style")]
        for key in sheet["group_order"]
    ]


def promote(values: Sequence[styles.Json], preferred: styles.Json) -> styles.Json:
    """Choose a modal structure and whole native sample at each fixed identity.

    Each non-absent child has one vote. Ties retain the parent's value when it
    participates, otherwise the first child wins; callers provide stable order.
    Group wrappers vote only among matching slot shapes, keeping their native
    childfields container compatible. Rows can vote across other shape changes.
    """
    parent = preferred
    children = values
    styles.validate(parent)
    sheets: list[styles.Json] = []
    for sheet in children:
        if "absent" in sheet:
            if sheet != {"absent": True} or sheet["absent"] is not True:
                raise ProjectError("An absent stylesheet requires only absent: true")
            continue
        styles.validate(sheet)
        sheets.append(sheet)
    if not sheets:
        return deepcopy(parent)

    shape = _mode([_shape(sheet) for sheet in sheets], _shape(parent))
    groups: styles.Json = {}
    for key, slots in shape:
        candidates = [
            sheet["groups"][key] for sheet in sheets if key in sheet["groups"]
        ]
        wrappers = [
            group["properties"]
            for group in candidates
            if numbered(group["styles"], "style") == slots
        ]
        previous = parent["groups"].get(key, {})
        group: styles.Json = {
            "properties": _mode(wrappers, previous.get("properties")),
            "styles": {},
        }
        for slot in slots:
            group["styles"][slot] = _mode(
                [
                    value["styles"][slot]
                    for value in candidates
                    if slot in value["styles"]
                ],
                previous.get("styles", {}).get(slot),
            )
        groups[key] = group
    result = {
        "properties": _mode(
            [sheet["properties"] for sheet in sheets], parent["properties"]
        ),
        "group_order": [key for key, _ in shape],
        "groups": groups,
    }
    styles.validate(result)
    return result

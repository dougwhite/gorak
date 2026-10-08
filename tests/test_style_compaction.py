"""Modal style-row promotion preserves native identity and ordered payloads."""

from copy import deepcopy
from typing import Any

import pytest
from lxml import etree

from gorak import native_styles as styles
from gorak.errors import ProjectError
from gorak.style_compaction import ordered_key, promote


def sheet(*groups: tuple[str, list[str]]) -> dict[str, Any]:
    root = etree.Element("fielddefaults")
    for name, widths in groups:
        group = etree.SubElement(root, "row")
        group.set("{http://www.w3.org/2001/XMLSchema-instance}type", "matrixfield")
        etree.SubElement(group, "clienttext").text = name
        children = etree.SubElement(group, "childfields")
        for width in widths:
            row = etree.SubElement(children, "row")
            row.set("{http://www.w3.org/2001/XMLSchema-instance}type", "entryfield")
            etree.SubElement(row, "width").text = width
    return styles.encode(root)


def test_independent_modal_rows_promote_without_equal_whole_sheets() -> None:
    parent = sheet(("entryfield", ["0", "0"]))
    values = [
        sheet(("entryfield", ["10", "20"])),
        sheet(("entryfield", ["10", "30"])),
        sheet(("entryfield", ["40", "30"])),
    ]
    original = deepcopy(values)
    result = promote(values, parent)
    assert result == sheet(("entryfield", ["10", "30"]))
    assert values == original
    assert ordered_key(promote(values, result)) == ordered_key(result)
    for value in values:
        assert ordered_key(
            styles.resolve(result, styles.difference(result, value))
        ) == ordered_key(value)


def test_duplicate_groups_and_slots_are_not_deduplicated_or_renumbered() -> None:
    parent = sheet(("entryfield", ["0", "0"]), ("entryfield", ["0"]))
    first = sheet(("entryfield", ["10", "10"]), ("entryfield", ["20"]))
    second = sheet(("entryfield", ["10", "30"]), ("entryfield", ["20"]))
    third = sheet(("entryfield", ["40", "30"]), ("entryfield", ["50"]))
    result = promote([first, second, third], parent)
    assert result["group_order"] == ["entryfield", "entryfield:2"]
    assert result == sheet(("entryfield", ["10", "30"]), ("entryfield", ["20"]))
    assert list(result["groups"]["entryfield"]["styles"]) == ["style1", "style2"]


def test_ties_prefer_parent_then_stable_child_order() -> None:
    first = sheet(("entryfield", ["10"]))
    second = sheet(("entryfield", ["20"]))
    assert promote([first, second], second) == second
    assert promote([first, second], sheet(("entryfield", ["0"]))) == first


def test_ordered_payloads_count_separately_and_preserve_native_order() -> None:
    first = sheet(("entryfield", ["10"]))
    row = first["groups"]["entryfield"]["styles"]["style1"]
    row["height"] = "20"
    second = deepcopy(first)
    second["groups"]["entryfield"]["styles"]["style1"] = {
        "_type": "entryfield",
        "height": "20",
        "width": "10",
    }
    assert first == second
    assert ordered_key(first) != ordered_key(second)
    result = promote([first, second, second], first)
    assert ordered_key(result) == ordered_key(second)
    reordered = sheet(("other", ["20"]), ("entryfield", ["10"]))
    assert promote([reordered, reordered, first], first)["group_order"] == [
        "other",
        "entryfield",
    ]


def test_absent_frames_do_not_vote_and_empty_values_remain_distinct() -> None:
    parent = sheet(("entryfield", ["10"]))
    assert promote([{"absent": True}], parent) == parent
    result = promote([], parent)
    assert result == parent and result is not parent
    empty = sheet(("entryfield", [""]))
    missing = deepcopy(empty)
    del missing["groups"]["entryfield"]["styles"]["style1"]["width"]
    assert promote([empty, empty, missing, {"absent": True}], parent) == empty
    assert promote([missing, missing, empty], parent) == missing
    with pytest.raises(ProjectError, match="absent"):
        promote([{"absent": True, "groups": {}}], parent)


def test_modal_shape_keeps_wrapper_compatible_and_missing_slots_explicit() -> None:
    parent = sheet(("entryfield", ["10", "20"]))
    no_slots = sheet(("entryfield", []))
    del no_slots["groups"]["entryfield"]["properties"]["childfields"]
    short = sheet(("entryfield", ["30"]))
    result = promote([no_slots, short, short], parent)
    assert result == short
    assert "childfields" in result["groups"]["entryfield"]["properties"]
    assert promote([no_slots, no_slots, short], parent) == no_slots
    assert promote([sheet(), sheet(), short], parent) == sheet()

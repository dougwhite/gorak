"""Absent stylesheets and property ordering must survive readable projection."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from gorak import native_styles as styles
from gorak.contract_source import equivalent
from gorak.errors import ProjectError
from gorak.parser import NS
from gorak.portable_source import restore_component
from gorak.style_commands import describe, maintain
from tests.native_source import write_component


@pytest.mark.parametrize("kind", ["framesource", "frametemplate"])
@pytest.mark.parametrize("present", [False, True])
def test_empty_stylesheets_export_in_native_absent_form(
    tmp_path: Path, kind: str, present: bool
) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    node = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{NS["xsi"]}" name="panel" xsi:type="{kind}">'
        '<topform width="1000"/></COMPONENT>'
    )
    if present:
        etree.SubElement(node, "fielddefaults")
    source = folder / "panel.w4gl"
    write_component(source, node)
    assert equivalent(node, restore_component(source))
    assert restore_component(source).find("fielddefaults") is None
    assert json.loads(source.with_suffix(".fielddefaults.json").read_text()) == {
        "absent": True
    }
    assert describe(tmp_path, "example", "panel") == {
        "stylesheet": {"absent": True},
        "entries": [],
    }
    for operation in ("compact", "publish", "compact"):
        maintain(tmp_path, operation)
        assert equivalent(node, restore_component(source))
    other = deepcopy(node)
    if present:
        other.remove(other.find("fielddefaults"))
    else:
        etree.SubElement(other, "fielddefaults")
    assert equivalent(node, other)
    style = other.find("fielddefaults")
    if style is None:
        style = etree.SubElement(other, "fielddefaults")
    etree.SubElement(style, "row_class").text = "matrixfield"
    assert not equivalent(node, other)


@pytest.mark.parametrize(
    "layer", [{"absent": False}, {"absent": 1}, {"absent": True, "groups": {}}]
)
def test_absent_marker_rejects_ambiguous_layers(layer: dict[str, Any]) -> None:
    with pytest.raises(ProjectError, match="absent: true"):
        styles.resolve_frame(styles.baseline(), layer)


def test_absent_marker_is_frame_only() -> None:
    with pytest.raises(ProjectError):
        styles.resolve(styles.baseline(), {"absent": True})


def test_markup_property_order_is_not_content(tmp_path: Path) -> None:
    node = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{NS["xsi"]}" name="panel" xsi:type="framesource">'
        '<topform><childfields><row xsi:type="entryfield"><name>value</name>'
        "<exactwidth>750</exactwidth><maxcharacters>12</maxcharacters>"
        '<script>on setvalue = {}</script></row><row xsi:type="buttonfield">'
        "<name>close</name></row><row_class>formfield</row_class>"
        "</childfields></topform><fielddefaults/></COMPONENT>"
    )
    source = tmp_path / "panel.w4gl"
    write_component(source, node)
    restored = restore_component(source)
    assert equivalent(node, restored)
    for tag in ("exactwidth", "maxcharacters", "script"):
        changed = deepcopy(restored)
        changed.find(f".//{tag}").text = "different"
        assert not equivalent(node, changed)
    reordered = deepcopy(restored)
    children = reordered.find("topform/childfields")
    children.insert(0, children[1])
    assert not equivalent(node, reordered)


def test_compaction_keeps_absent_frame_when_sibling_styles_are_promoted(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    for name in ("unstyled", "styled"):
        node = etree.fromstring(
            f'<COMPONENT xmlns:xsi="{NS["xsi"]}" name="{name}" xsi:type="framesource">'
            "<topform/></COMPONENT>"
        )
        if name == "styled":
            etree.SubElement(
                etree.SubElement(node, "fielddefaults"), "row_class"
            ).text = "matrixfield"
        write_component(folder / f"{name}.w4gl", node)
    maintain(tmp_path, "compact")
    assert restore_component(folder / "unstyled.w4gl").find("fielddefaults") is None
    assert restore_component(folder / "styled.w4gl").find("fielddefaults") is not None
    # Removing the explicit absence marker restores ordinary stylesheet inheritance.
    (folder / "unstyled.fielddefaults.json").unlink()
    assert restore_component(folder / "unstyled.w4gl").find("fielddefaults") is not None

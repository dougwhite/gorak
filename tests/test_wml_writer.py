from copy import deepcopy
from pathlib import Path

import pytest
from lxml import etree

from gorak.importer import signature
from gorak.parser import encode_wml, parse_component_node, serialize_wml
from gorak.project import ProjectError
from gorak.wml_writer import overlay_markup


def frame() -> etree._Element:
    node = etree.parse("tests/fixtures/fm_example_frame.xml").find("COMPONENT")
    assert node is not None
    return node


@pytest.mark.parametrize(
    "edit", ["move", "label", "add", "delete", "reorder", "script"]
)
def test_layout_roundtrip_preserves_unedited_xml(tmp_path: Path, edit: str) -> None:
    node = frame()
    original = deepcopy(node)
    tree = etree.fromstring((encode_wml(parse_component_node(node)) or "").encode())
    field = tree.find(".//entryfield")
    assert field is not None
    parent = field.getparent()
    assert parent is not None
    if edit == "move":
        field.set("xleft", "321")
    elif edit == "label":
        field.set("defaultstring", "Ready")
    elif edit == "add":
        extra = etree.SubElement(
            parent,
            "entryfield",
            name="new_output",
            xleft="300",
            ytop="700",
            width="1200",
        )
        etree.SubElement(extra, "script").text = etree.CDATA(
            "ON setvalue = { MESSAGE 'Changed'; }"
        )
    elif edit == "delete":
        parent.remove(field)
    elif edit == "reorder":
        parent.remove(field)
        parent.insert(0, field)
    else:
        event = tree.find(".//script")
        assert event is not None
        event.text = etree.CDATA("ON click = { MESSAGE 'Ready'; }")
    path = tmp_path / "frame.wml"
    path.write_text(serialize_wml(tree))
    overlay_markup(node, path)
    actual = etree.fromstring((encode_wml(parse_component_node(node)) or "").encode())
    assert signature(actual) == signature(tree)
    assert signature(node.find("fielddefaults")) == signature(
        original.find("fielddefaults")
    )
    assert node.findtext("script") == original.findtext("script")


def test_unknown_attribute_rejected(tmp_path: Path) -> None:
    node = frame()
    markup = encode_wml(parse_component_node(node)) or ""
    tree = etree.fromstring(markup.encode())
    tree.find(".//entryfield").set("misspelled_property", "1")
    path = tmp_path / "frame.wml"
    path.write_bytes(etree.tostring(tree))
    with pytest.raises(ProjectError, match="Unsupported scalar"):
        overlay_markup(node, path)


def test_new_positioned_control_does_not_inherit_palette_alignment(
    tmp_path: Path,
) -> None:
    node = frame()
    tree = etree.fromstring((encode_wml(parse_component_node(node)) or "").encode())
    parent = tree.find(".//subform")
    assert parent is not None
    etree.SubElement(parent, "entryfield", name="positioned", xleft="104", ytop="104")
    path = tmp_path / "frame.wml"
    path.write_bytes(etree.tostring(tree))
    overlay_markup(node, path)
    added = next(
        r
        for r in node.findall(".//childfields/row")
        if r.findtext("name") == "positioned"
    )
    assert added.find("gravity") is None
    assert added.findtext("xleft") == "104"
    assert added.findtext("ytop") == "104"


@pytest.mark.parametrize(
    "text",
    [
        '<!DOCTYPE frame [<!ENTITY x SYSTEM "file:///not-read">]><frame><topform/></frame>',
        '<frame><topform unknown="1"/></frame>',
        '<frame><topform><classsource name="not_a_control"/></topform></frame>',
    ],
)
def test_invalid_markup_fails_before_import(tmp_path: Path, text: str) -> None:
    path = tmp_path / "frame.wml"
    path.write_text(text)
    with pytest.raises(ProjectError):
        overlay_markup(frame(), path)

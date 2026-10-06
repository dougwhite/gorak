"""Default modes are implicit only for layout fields, not arbitrary metadata."""

from copy import deepcopy

import pytest
from lxml import etree

from gorak.contract_source import equivalent, markup_node
from gorak.parser import MarkupDefaultsIndex, frame_markup_element

INDEX = MarkupDefaultsIndex({}, {}, explicit=True)
XSI = "http://www.w3.org/2001/XMLSchema-instance"


@pytest.mark.parametrize(
    "kind", ["entryfield", "stackfield", "buttonfield", "menuitem"]
)
@pytest.mark.parametrize("mode", [None, "0", "1", "2", "3", "", "99"])
def test_modes_roundtrip(kind: str, mode: str | None) -> None:
    source = etree.fromstring(
        f'<row xmlns:xsi="{XSI}" xsi:type="{kind}"><name>value</name>'
        "<defaultstring>7</defaultstring></row>"
    )
    if mode is not None:
        etree.SubElement(source, "defaultvalue").text = mode
    markup = frame_markup_element(source, INDEX)
    assert markup.get("defaultvalue") == (None if mode in (None, "1") else mode)
    assert markup.get("defaultstring") == "7"
    restored = markup_node(markup, "row", kind, INDEX)
    assert restored.findtext("defaultvalue") == ("1" if mode is None else mode)
    assert restored.findtext("defaultstring") == "7"


@pytest.mark.parametrize(
    "wrapper,kind",
    [
        ("topform", "frameform"),
        ("viewfield", "entryfield"),
        ("protofield", "entryfield"),
        ("framefield", "entryfield"),
        ("reportfield", "entryfield"),
    ],
)
def test_nested_field_wrappers(wrapper: str, kind: str) -> None:
    root = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{XSI}" xsi:type="framesource">'
        f'<{wrapper} xsi:type="{kind}"><defaultvalue>1</defaultvalue></{wrapper}>'
        "</COMPONENT>"
    )
    markup = frame_markup_element(root[0], INDEX)
    assert markup.get("defaultvalue") is None
    assert markup_node(markup, wrapper, kind, INDEX).findtext("defaultvalue") == "1"


def test_comparison_accepts_only_system_mode_normalization() -> None:
    left = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{XSI}" xsi:type="framesource" name="sample">'
        '<topform><childfields><row xsi:type="entryfield"><name>value</name>'
        "<defaultstring>7</defaultstring></row><row_class>formfield</row_class>"
        "</childfields></topform></COMPONENT>"
    )
    right = deepcopy(left)
    field = right.find(".//row")
    assert field is not None
    mode = etree.SubElement(field, "defaultvalue")
    mode.text = "1"
    assert equivalent(left, right)
    for value in ["0", "2", "3", "", "99"]:
        mode.text = value
        assert not equivalent(left, right)
    mode.text = "1"
    field.find("defaultstring").text = "8"
    assert not equivalent(left, right)
    right = deepcopy(left)
    etree.SubElement(right, "defaultvalue").text = "1"
    assert not equivalent(left, right)


def test_stylesheets_remain_exact() -> None:
    left = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{XSI}" xsi:type="framesource" name="sample">'
        "<fielddefaults><row><clienttext>entryfield</clienttext><childfields>"
        '<row xsi:type="entryfield"><defaultvalue>1</defaultvalue></row>'
        "<row_class>formfield</row_class></childfields></row>"
        "<row_class>fieldobject</row_class></fielddefaults><topform/></COMPONENT>"
    )
    right = deepcopy(left)
    mode = right.find(".//defaultvalue")
    mode.getparent().remove(mode)
    assert not equivalent(left, right)


def test_untyped_native_property_wrappers_and_collection_rows() -> None:
    root = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{XSI}" xsi:type="framesource">'
        "<topform><defaultvalue>1</defaultvalue><childfields>"
        '<row xsi:type="tabfolder"><tabpagearray><row><name>page</name>'
        "<defaultvalue>1</defaultvalue></row><row_class>tabpage</row_class>"
        "</tabpagearray></row><row_class>formfield</row_class>"
        "</childfields></topform><mainbartop><row><defaultvalue>1</defaultvalue>"
        "</row><row_class>mainbar</row_class></mainbartop></COMPONENT>"
    )
    top = frame_markup_element(root[0], INDEX)
    assert top.get("defaultvalue") is None
    assert top.find(".//tabpagearray/row").get("defaultvalue") is None
    restored = markup_node(top, "topform", "frameform", INDEX)
    assert restored.findtext("defaultvalue") == "1"
    assert restored.findtext(".//tabpagearray/row/defaultvalue") == "1"
    bar = frame_markup_element(root[1], INDEX)
    assert bar.get("defaultvalue") is None
    assert markup_node(bar, "row", "mainbar", INDEX).findtext("defaultvalue") == "1"

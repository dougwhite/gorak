from pathlib import Path
from typing import Any

from lxml import etree

from gorak.field_defaults import (
    parse_field_defaults_node,
)

GORAK_EXAMPLES_PATH = Path(__file__).parent / "fixtures" / "gorak_examples.xml"


def field_defaults_node() -> etree._Element:
    node = etree.parse(GORAK_EXAMPLES_PATH).find(".//fielddefaults")
    assert node is not None
    return node


def test_parse_field_defaults_preserves_ordered_field_styles() -> None:
    defaults = parse_field_defaults_node(field_defaults_node())
    field_styles = defaults["field_styles"]

    assert field_styles[0] == {
        "type": "barfield",
        "group": "barfield",
        "properties": {
            "datatype": "i4",
            "defaultvalue": "3",
            "defaultstring": "0",
            "bgcolor": "84",
            "fgcolor": "70",
            "xleft": "271",
            "ytop": "52",
            "width": "740",
            "height": "521",
            "designbias": "4",
            "trimbias": "256",
            "updatebias": "16",
            "querybias": "16",
            "readbias": "32",
            "user1bias": "16",
            "user2bias": "16",
            "user3bias": "16",
            "gravity": "17",
            "bgpattern": "-1",
            "bgdisplaypolicy": "2",
            "focusbehavior": "2",
            "outlinecolor": "1",
            "outlinestyle": "4",
            "fgpattern": "-1",
            "growfrom": "6",
        },
    }
    assert [
        style["group"] for style in field_styles if style["type"] == "entryfield"
    ] == [
        "entryfield",
        "entryfield:2",
    ]
    assert [
        style["group"] for style in field_styles if style["type"] == "rectangleshape"
    ] == ["rectangleshape", "rectangleshape"]


def test_parse_field_defaults_preserves_nested_property_subtrees() -> None:
    defaults = parse_field_defaults_node(field_defaults_node())

    assert_nested_property(defaults, "controlbutton", "optionmenu", "bgcolor")
    assert_nested_property(defaults, "flexibleform", "childfields", "row")
    assert_nested_property(defaults, "imagetrim", "image", "obj_encoded")
    assert_nested_property(defaults, "listfield", "valuelist", "choiceitems")
    assert_nested_property(defaults, "listviewfield", "colattributes", "row")
    assert_nested_property(defaults, "matrixfield", "childfields", "row")
    assert_nested_property(defaults, "optionfield", "valuelist", "choiceitems")
    assert_nested_property(defaults, "palettefield", "valuelist", "choiceitems")
    assert_nested_property(defaults, "popupbutton", "optionmenu", "bgcolor")
    assert_nested_property(defaults, "radiofield", "valuelist", "choiceitems")
    assert_nested_property(defaults, "stackfield", "childfields", "row")
    assert_nested_property(defaults, "tabfolder", "tabbar", "bgcolor")
    assert_nested_property(defaults, "tabfolder", "tabpagearray", "row")
    assert_nested_property(defaults, "tablefield", "controlbutton", "name")
    assert_nested_property(defaults, "tablefield", "tablebody", "bgcolor")
    assert_nested_property(defaults, "tablefield", "tableheader", "bgcolor")
    assert_nested_property(defaults, "tablefield", "titletrim", "bgcolor")
    assert_nested_property(defaults, "viewportfield", "viewfield", "bgcolor")


def assert_nested_property(
    defaults: dict[str, Any],
    field_type: str,
    property_name: str,
    nested_key: str,
) -> None:
    style = next(
        style
        for style in defaults["field_styles"]
        if style["type"] == field_type and property_name in style["properties"]
    )

    value = style["properties"][property_name]
    assert isinstance(value, dict), f"{field_type}.{property_name}"
    assert nested_key in value, f"{field_type}.{property_name}.{nested_key}"

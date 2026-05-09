from pathlib import Path
from typing import Any

from lxml import etree

from gorak.field_defaults import (
    common_defaults,
    diff_defaults,
    effective_defaults,
    flatten_app_defaults,
    merge_defaults,
    parse_field_defaults_node,
    remove_defaults,
)

GORAK_EXAMPLES_PATH = Path(__file__).parent / "fixtures" / "gorak_examples.xml"


def field_defaults_node() -> etree._Element:
    node = etree.parse(GORAK_EXAMPLES_PATH).find(".//fielddefaults")
    assert node is not None
    return node


def test_parse_field_defaults_has_common_model_container() -> None:
    defaults = parse_field_defaults_node(field_defaults_node())

    assert defaults["common_model_container"] == {
        "type": "matrixfield",
        "properties": {
            "bgcolor": "2",
            "fgcolor": "1",
            "width": "10416",
            "height": "10417",
            "designbias": "2",
            "trimbias": "8",
            "updatebias": "16",
            "querybias": "16",
            "readbias": "32",
            "user1bias": "16",
            "user2bias": "16",
            "user3bias": "16",
            "fieldstyle": "0",
            "bgpattern": "1",
            "focusbehavior": "1",
            "outlinecolor": "1",
        },
    }


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
    assert [style["group"] for style in field_styles if style["type"] == "entryfield"] == [
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


def test_merge_defaults_applies_nested_overrides_without_mutating_parent() -> None:
    parent: dict[str, Any] = {
        "common_model_container": {
            "properties": {"bgcolor": "2", "fgcolor": "1"}
        }
    }
    override: dict[str, Any] = {
        "common_model_container": {"properties": {"bgcolor": "70"}}
    }

    merged = merge_defaults(parent, override)

    assert merged == {
        "common_model_container": {
            "properties": {"bgcolor": "70", "fgcolor": "1"}
        }
    }
    assert parent["common_model_container"]["properties"]["bgcolor"] == "2"


def test_diff_defaults_returns_only_values_that_differ_from_parent() -> None:
    parent: dict[str, Any] = {
        "common_model_container": {
            "properties": {"bgcolor": "2", "fgcolor": "1"}
        }
    }
    child: dict[str, Any] = {
        "common_model_container": {
            "properties": {"bgcolor": "70", "fgcolor": "1"}
        },
        "field_styles": [
            {"type": "entryfield", "group": "entryfield", "properties": {"bgcolor": "84"}}
        ],
    }

    assert diff_defaults(parent, child) == {
        "common_model_container": {"properties": {"bgcolor": "70"}},
        "field_styles": [
            {"type": "entryfield", "group": "entryfield", "properties": {"bgcolor": "84"}}
        ],
    }


def test_diff_defaults_preserves_changed_nested_subtrees() -> None:
    parent: dict[str, Any] = {
        "field_styles": [
            {
                "type": "controlbutton",
                "group": "controlbutton",
                "properties": {"optionmenu": {"bgcolor": "2", "fgcolor": "1"}},
            }
        ]
    }
    child: dict[str, Any] = {
        "field_styles": [
            {
                "type": "controlbutton",
                "group": "controlbutton",
                "properties": {"optionmenu": {"bgcolor": "70", "fgcolor": "1"}},
            }
        ]
    }

    assert diff_defaults(parent, child) == child


def test_effective_defaults_merges_repo_app_and_frame_overrides() -> None:
    repo: dict[str, Any] = {
        "common_model_container": {"properties": {"bgcolor": "2"}}
    }
    app: dict[str, Any] = {
        "common_model_container": {"properties": {"fgcolor": "1"}}
    }
    frame: dict[str, Any] = {
        "field_styles": [
            {"type": "entryfield", "group": "entryfield", "properties": {"bgcolor": "84"}}
        ]
    }

    assert effective_defaults(repo, app, frame) == {
        "common_model_container": {"properties": {"bgcolor": "2", "fgcolor": "1"}},
        "field_styles": [
            {"type": "entryfield", "group": "entryfield", "properties": {"bgcolor": "84"}}
        ],
    }


def test_common_defaults_returns_values_shared_by_every_child() -> None:
    assert common_defaults(
        [
            {"common_model_container": {"properties": {"bgcolor": "2"}}},
            {"common_model_container": {"properties": {"bgcolor": "2"}}},
        ]
    ) == {"common_model_container": {"properties": {"bgcolor": "2"}}}


def test_remove_defaults_removes_matching_nested_values() -> None:
    assert remove_defaults(
        {
            "common_model_container": {
                "properties": {"bgcolor": "2", "fgcolor": "1"}
            }
        },
        {"common_model_container": {"properties": {"bgcolor": "2"}}},
    ) == {"common_model_container": {"properties": {"fgcolor": "1"}}}


def test_flatten_app_defaults_moves_shared_values_to_repo(tmp_path: Path) -> None:
    (tmp_path / "field_defaults.json").write_text("{}\n")
    for app_name in ["orders", "billing"]:
        app_dir = tmp_path / app_name
        app_dir.mkdir()
        (app_dir / "app.json").write_text("{}\n")
        (app_dir / "field_defaults.json").write_text(
            """
{
    "common_model_container": {
        "properties": {
            "bgcolor": "2",
            "fgcolor": "1"
        }
    }
}
""".strip()
            + "\n"
        )

    result = flatten_app_defaults(tmp_path)

    assert result.promoted_values == 2
    assert (tmp_path / "field_defaults.json").read_text() == (
        "{\n"
        '    "common_model_container": {\n'
        '        "properties": {\n'
        '            "bgcolor": "2",\n'
        '            "fgcolor": "1"\n'
        "        }\n"
        "    }\n"
        "}\n"
    )
    assert (tmp_path / "orders" / "field_defaults.json").read_text() == "{}\n"
    assert (tmp_path / "billing" / "field_defaults.json").read_text() == "{}\n"

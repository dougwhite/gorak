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


def test_parse_field_defaults_uses_field_type_keys() -> None:
    defaults = parse_field_defaults_node(field_defaults_node())

    assert "barfield" in defaults["field_types"]
    assert "entryfield" in defaults["field_types"]


def test_parse_field_defaults_preserves_matrix_and_child_properties() -> None:
    defaults = parse_field_defaults_node(field_defaults_node())
    barfield = defaults["field_types"]["barfield"]

    assert barfield["type"] == "matrixfield"
    assert barfield["properties"]["bgcolor"] == "2"
    assert barfield["properties"]["fgcolor"] == "1"
    assert barfield["properties"]["columns"] == "1"
    assert barfield["properties"]["rows"] == "1"
    assert barfield["childfields"] == [
        {
            "type": "barfield",
            "attributes": {"row": "1", "column": "1"},
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
    ]


def test_merge_defaults_applies_nested_overrides_without_mutating_parent() -> None:
    parent: dict[str, Any] = {
        "field_types": {
            "entryfield": {
                "properties": {"bgcolor": "84", "fgcolor": "86"},
                "childfields": [{"properties": {"width": "896"}}],
            }
        }
    }
    override: dict[str, Any] = {
        "field_types": {
            "entryfield": {
                "properties": {"bgcolor": "70"},
            }
        }
    }

    merged = merge_defaults(parent, override)

    assert merged == {
        "field_types": {
            "entryfield": {
                "properties": {"bgcolor": "70", "fgcolor": "86"},
                "childfields": [{"properties": {"width": "896"}}],
            }
        }
    }
    assert parent["field_types"]["entryfield"]["properties"]["bgcolor"] == "84"


def test_diff_defaults_returns_only_values_that_differ_from_parent() -> None:
    parent: dict[str, Any] = {
        "field_types": {
            "entryfield": {
                "properties": {"bgcolor": "84", "fgcolor": "86"},
                "childfields": [{"properties": {"width": "896"}}],
            }
        }
    }
    child: dict[str, Any] = {
        "field_types": {
            "entryfield": {
                "properties": {"bgcolor": "70", "fgcolor": "86"},
                "childfields": [{"properties": {"width": "896"}}],
            },
            "buttonfield": {"properties": {"textlabel": "Button"}},
        }
    }

    assert diff_defaults(parent, child) == {
        "field_types": {
            "entryfield": {"properties": {"bgcolor": "70"}},
            "buttonfield": {"properties": {"textlabel": "Button"}},
        }
    }


def test_effective_defaults_merges_repo_app_and_frame_overrides() -> None:
    repo: dict[str, Any] = {
        "field_types": {"entryfield": {"properties": {"bgcolor": "84"}}}
    }
    app: dict[str, Any] = {
        "field_types": {"entryfield": {"properties": {"fgcolor": "86"}}}
    }
    frame: dict[str, Any] = {
        "field_types": {"entryfield": {"properties": {"bgcolor": "70"}}}
    }

    assert effective_defaults(repo, app, frame) == {
        "field_types": {
            "entryfield": {
                "properties": {
                    "bgcolor": "70",
                    "fgcolor": "86",
                }
            }
        }
    }


def test_common_defaults_returns_values_shared_by_every_child() -> None:
    assert common_defaults(
        [
            {
                "field_types": {
                    "entryfield": {
                        "properties": {"bgcolor": "70", "fgcolor": "86"}
                    }
                }
            },
            {
                "field_types": {
                    "entryfield": {
                        "properties": {"bgcolor": "70", "fgcolor": "72"}
                    }
                }
            },
        ]
    ) == {
        "field_types": {"entryfield": {"properties": {"bgcolor": "70"}}}
    }


def test_remove_defaults_removes_matching_nested_values() -> None:
    assert remove_defaults(
        {
            "field_types": {
                "entryfield": {
                    "properties": {"bgcolor": "70", "fgcolor": "86"}
                }
            }
        },
        {"field_types": {"entryfield": {"properties": {"bgcolor": "70"}}}},
    ) == {"field_types": {"entryfield": {"properties": {"fgcolor": "86"}}}}


def test_flatten_app_defaults_moves_shared_values_to_repo(tmp_path: Path) -> None:
    (tmp_path / "field_defaults.json").write_text('{"field_types": {}}\n')
    for app_name in ["orders", "billing"]:
        app_dir = tmp_path / app_name
        app_dir.mkdir()
        (app_dir / "app.json").write_text("{}\n")
        (app_dir / "field_defaults.json").write_text(
            """
{
    "field_types": {
        "entryfield": {
            "properties": {
                "bgcolor": "70",
                "fgcolor": "86"
            }
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
        '    "field_types": {\n'
        '        "entryfield": {\n'
        '            "properties": {\n'
        '                "bgcolor": "70",\n'
        '                "fgcolor": "86"\n'
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    assert (tmp_path / "orders" / "field_defaults.json").read_text() == "{}\n"
    assert (tmp_path / "billing" / "field_defaults.json").read_text() == "{}\n"

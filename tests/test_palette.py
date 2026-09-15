from copy import deepcopy
from pathlib import Path
from typing import Any

from lxml import etree

from gorak.importer import signature
from gorak.palette import decode, difference, encode, merge, parent_defaults, prepare
from gorak.project import read_json, write_json
from gorak.readable_source import decode_component, encode_component


def frame() -> etree._Element:
    node = etree.parse("tests/fixtures/fm_example_frame.xml").find("COMPONENT")
    assert node is not None
    return node


def write_frame(folder: Path, name: str, node: etree._Element) -> Path:
    node = deepcopy(node)
    node.set("name", name)
    text, markup = encode_component(node, defaults=parent_defaults(folder))
    path = folder / f"{name}.w4gl"
    path.write_text(text)
    path.with_suffix(".wml").write_text(markup or "")
    return path


def test_only_differences_and_three_level_precedence(tmp_path: Path) -> None:
    folder = tmp_path / "app"
    folder.mkdir()
    node = frame()
    prepare(tmp_path, folder, [node])
    root = read_json(tmp_path / "field_defaults.json")
    app = deepcopy(root)
    app["field_styles"][0]["properties"]["bgcolor"] = "20"
    write_json(folder / "field_defaults.json", difference(root, app))
    desired = deepcopy(app)
    desired["field_styles"][0]["properties"]["bgcolor"] = "30"
    defaults = node.find("fielddefaults")
    assert defaults is not None
    node.replace(defaults, decode(desired))
    path = write_frame(folder, "panel", node)
    assert "[framesource.fielddefaults]" not in path.read_text()
    assert "[fielddefaults.field_styles.properties]" in path.read_text()
    assert 'bgcolor = "30"' in path.read_text()
    assert len(path.read_text().splitlines()) < 100
    restored = decode_component(path)
    assert encode(restored.find("fielddefaults")) == desired
    # Unoverridden properties propagate from the authoritative root.
    root["field_styles"][0]["properties"]["fgcolor"] = "42"
    write_json(tmp_path / "field_defaults.json", root)
    actual = encode(decode_component(path).find("fielddefaults"))
    assert actual["field_styles"][0]["properties"]["fgcolor"] == "42"
    assert actual["field_styles"][0]["properties"]["bgcolor"] == "30"
    assert read_json(folder / "field_defaults.json") == {
        "field_styles": [
            {
                "type": app["field_styles"][0]["type"],
                "group": app["field_styles"][0]["group"],
                "properties": {"bgcolor": "20"},
            }
        ]
    }


def test_equal_frame_has_no_palette_payload(tmp_path: Path) -> None:
    folder = tmp_path / "app"
    folder.mkdir()
    node = frame()
    prepare(tmp_path, folder, [node])
    path = write_frame(folder, str(node.get("name")), node)
    assert "fielddefaults" not in path.read_text()
    assert read_json(folder / "field_defaults.json") == {}
    assert signature(decode_component(path)) == signature(node)
    assert not list(tmp_path.rglob("*.xml"))


def test_existing_root_is_authoritative(tmp_path: Path) -> None:
    from gorak.field_defaults import parse_field_defaults_node

    folder = tmp_path / "app"
    folder.mkdir()
    node = frame()
    original = parse_field_defaults_node(node.find("fielddefaults"))
    original["field_styles"][0]["properties"]["bgcolor"] = "99"
    write_json(tmp_path / "field_defaults.json", original)
    prepare(tmp_path, folder, [node])
    root = read_json(tmp_path / "field_defaults.json")
    assert parse_field_defaults_node(decode(root)) == original
    path = write_frame(folder, str(node.get("name")), node)
    assert signature(decode_component(path)) == signature(node)


def test_deletion_and_duplicate_style_override() -> None:
    first: dict[str, Any] = {
        "type": "entryfield",
        "group": "entries",
        "properties": {"width": "100", "height": "20"},
    }
    parent = {"field_styles": [first, deepcopy(first)]}
    child = deepcopy(parent)
    child["field_styles"][1]["properties"]["width"] = "200"
    del child["field_styles"][1]["properties"]["height"]
    delta = difference(parent, child)
    assert delta["field_styles"][0]["occurrence"] == 2
    assert merge(parent, delta) == child
    reordered = {"field_styles": [first]}
    assert merge(parent, difference(parent, reordered)) == reordered


def test_flatten_preserves_effective_inherited_palettes(tmp_path: Path) -> None:
    from gorak.field_defaults import flatten_app_defaults

    node = frame()
    paths = []
    for name in ["one", "two"]:
        folder = tmp_path / name
        folder.mkdir()
        write_json(folder / "app.json", {})
        prepare(tmp_path, folder, [node])
        root = read_json(tmp_path / "field_defaults.json")
        desired = deepcopy(root)
        desired["field_styles"][0]["properties"]["bgcolor"] = "99"
        write_json(folder / "field_defaults.json", difference(root, desired))
        replacement = deepcopy(node)
        replacement.replace(replacement.find("fielddefaults"), decode(desired))
        paths.append(write_frame(folder, "panel", replacement))
    before = [signature(decode_component(path)) for path in paths]
    flatten_app_defaults(tmp_path)
    assert [signature(decode_component(path)) for path in paths] == before
    assert all(read_json(p.parent / "field_defaults.json") == {} for p in paths)
    assert (
        read_json(tmp_path / "field_defaults.json")["field_styles"][0]["properties"][
            "bgcolor"
        ]
        == "99"
    )


def test_unplaced_styles_are_rejected() -> None:
    import pytest

    from gorak.errors import ProjectError

    defaults = encode(frame().find("fielddefaults"))
    defaults["field_styles"][0]["group"] = "missing"
    with pytest.raises(ProjectError, match="no palette group"):
        decode(defaults)

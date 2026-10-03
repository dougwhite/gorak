"""Current JSON-only stylesheet inheritance and rejection of older source."""

import json
from pathlib import Path
from typing import Any

import pytest

from gorak import native_styles as styles
from gorak.component_defaults import write_component_defaults
from gorak.contract_source import decode_component
from gorak.errors import ProjectError
from tests.test_native_styles import export, stylesheet, write


def test_each_layer_overrides_only_its_named_properties(tmp_path: Path) -> None:
    source = export(tmp_path)
    write(tmp_path / "field_defaults.json", styles.complete(stylesheet()))
    write(
        source.parent / "field_defaults.json",
        {"groups": {"entryfield": {"styles": {"style2": {"width": "200"}}}}},
    )
    child = {"groups": {"entryfield": {"styles": {"style2": {"fieldstyle": "2"}}}}}
    write_component_defaults(source, child)
    assert json.loads(source.with_suffix(".fielddefaults.json").read_text()) == child
    effective = styles.frame_styles(source)["groups"]["entryfield"]["styles"]
    assert effective["style1"]["width"] == "0"
    assert effective["style2"] == {
        "_type": "entryfield",
        "width": "200",
        "fieldstyle": "2",
    }
    write_component_defaults(
        source, {"groups": {"entryfield": {"styles": {"style2": {"width": "200"}}}}}
    )
    assert not source.with_suffix(".fielddefaults.json").exists()


@pytest.mark.parametrize(
    "old",
    [{"field_styles": []}, {"schema": "gorak-native-styles-v2"}, {"structure": []}],
)
def test_old_stylesheet_shapes_are_rejected(
    tmp_path: Path, old: dict[str, Any]
) -> None:
    source = export(tmp_path)
    write(source.with_suffix(".fielddefaults.json"), old)
    with pytest.raises(ProjectError, match="re-export"):
        decode_component(source)


def test_inline_defaults_are_rejected(tmp_path: Path) -> None:
    source = export(tmp_path)
    text = source.read_text()
    header, separator, script = text.partition("===")
    source.write_text(header + "\n[fielddefaults]\n\n" + separator + script)
    with pytest.raises(ProjectError, match="Inline field defaults"):
        decode_component(source)


@pytest.mark.parametrize(
    "command", [["styles", "migrate"], ["migrate-source"], ["defaults", "flatten"]]
)
def test_removed_migration_commands_are_not_offered(command: list[str]) -> None:
    from gorak.cli import build_parser

    with pytest.raises(SystemExit) as ex:
        build_parser().parse_args(command)
    assert ex.value.code == 2

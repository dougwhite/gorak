"""Ambiguous palettes preserve effective properties, not just lossy projections."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from gorak import cli, export, importer, push, sync_plan
from gorak.connection import OpenRoadConnection
from gorak.contract_source import decode_component, equivalent, palette_node
from gorak.domain import Application
from gorak.errors import ProjectError
from gorak.field_defaults import effective_defaults
from gorak.parser import NS, encode_w4gl, parse_component_node
from gorak.portable_source import comparison_component, overlay_component
from gorak.sync_guard import save_binding
from gorak.xml_writer import document, new_application


def source(root: Path) -> tuple[Path, dict[str, Any]]:
    folder = root / "example"
    folder.mkdir()
    (root / "gorak.json").write_text('{"name":"example"}')
    (root / ".env").write_text(
        "GORAK_BACKEND=local\nGORAK_VNODE=node\nGORAK_DATABASE=source\n"
    )
    (folder / "app.json").write_text("{}")
    defaults = {
        "common_model_container": {"type": "matrixfield", "properties": {}},
        "field_styles": [
            {
                "type": "tablefield",
                "group": "first",
                "properties": {"fgcolor": "2", "hasheaderbuttons": "1"},
            },
            {"type": "buttonfield", "group": "button", "properties": {"bgcolor": "3"}},
            {
                "type": "tablefield",
                "group": "second",
                "properties": {"fgcolor": "5", "hasheaderbuttons": "0"},
            },
        ],
    }
    (root / "field_defaults.json").write_text(json.dumps(defaults))
    (folder / "field_defaults.json").write_text("{}")
    path = folder / "panel.w4gl"
    path.write_text("[framesource]\n===\ninitialize()={}")
    return path, defaults


def native(defaults: dict[str, Any]) -> etree._Element:
    node = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{NS["xsi"]}" name="panel" xsi:type="framesource"><script>initialize()={{}}</script><topform><childfields><row xsi:type="tablefield"><name>items</name><fgcolor>5</fgcolor><hasheaderbuttons>0</hasheaderbuttons></row><row_class>formfield</row_class></childfields></topform></COMPONENT>'
    )
    node.append(palette_node(defaults))
    return node


def write_projection(path: Path, node: etree._Element) -> str:
    component = parse_component_node(node)
    # Use the repository palette rather than duplicating it in the frame.
    component.props.pop("fielddefaults", None)
    path.write_text(encode_w4gl(component))
    assert component.markup is not None
    path.with_suffix(".wml").write_text(component.markup)
    return component.markup


def properties(node: etree._Element) -> tuple[str | None, str | None]:
    field = node.find("topform/childfields/row")
    assert field is not None and field.find("gorak_style") is None
    assert field.get("gorak_style") is None
    return field.findtext("fgcolor"), field.findtext("hasheaderbuttons")


def test_second_style_preserves_actual_values_and_repeated_projection(
    tmp_path: Path,
) -> None:
    path, defaults = source(tmp_path)
    original = native(defaults)
    text = write_projection(path, original)
    assert 'gorak_style="2"' in text
    for _ in range(3):
        rebuilt = decode_component(path)
        assert properties(rebuilt) == ("5", "0")
        assert write_projection(path, rebuilt) == text
    wrong = deepcopy(rebuilt)
    wrong.find("topform/childfields/row/fgcolor").text = "2"
    wrong.find("topform/childfields/row/hasheaderbuttons").text = "1"
    assert not equivalent(rebuilt, wrong)


def test_selector_overrides_and_inheritance_apply_in_same_order(tmp_path: Path) -> None:
    path, defaults = source(tmp_path)
    app = {
        "field_styles": [
            {"type": "tablefield", "group": "second", "properties": {"fgcolor": "6"}}
        ]
    }
    frame = {
        "field_styles": [
            {
                "type": "tablefield",
                "group": "second",
                "properties": {"hasheaderbuttons": "1"},
            }
        ]
    }
    (path.parent / "field_defaults.json").write_text(json.dumps(app))
    path.write_text(
        '[framesource]\n[[fielddefaults.field_styles]]\ntype="tablefield"\ngroup="second"\n[fielddefaults.field_styles.properties]\nhasheaderbuttons="1"\n===\ninitialize()={}'
    )
    path.with_suffix(".wml").write_text(
        '<frame><topform><tablefield name="items" gorak_style="2" fgcolor="2"/></topform></frame>'
    )
    assert properties(decode_component(path)) == ("2", "1")
    merged = effective_defaults(defaults, app, frame)
    assert [s["group"] for s in merged["field_styles"]] == ["first", "button", "second"]
    baseline = native(defaults)
    write_projection(path, baseline)
    # Restore explicit selection after writing the baseline projection.
    path.with_suffix(".wml").write_text(
        '<frame><topform><tablefield name="items" gorak_style="1" fgcolor="7"/></topform></frame>'
    )
    actual = overlay_component(baseline, path)
    assert properties(actual) == ("7", "1")
    cache = tmp_path / ".openroad/example"
    cache.mkdir(parents=True)
    (cache / "panel.xml").write_bytes(document([native(defaults)]))
    assert properties(comparison_component(path)) == ("7", "1")


@pytest.mark.parametrize("explicit", [False, True])
def test_harmless_multiple_styles_need_no_selector(
    tmp_path: Path, explicit: bool
) -> None:
    path, defaults = source(tmp_path)
    if not explicit:
        defaults["field_styles"][0]["properties"] = {
            "fgcolor": "5",
            "hasheaderbuttons": "0",
        }
        (tmp_path / "field_defaults.json").write_text(json.dumps(defaults))
    node = native(defaults)
    if explicit:
        node.find("topform/childfields/row/fgcolor").text = "7"
        node.find("topform/childfields/row/hasheaderbuttons").text = "9"
    text = write_projection(path, node)
    assert "gorak_style" not in text
    assert properties(decode_component(path)) == (
        ("7", "9") if explicit else ("5", "0")
    )


@pytest.mark.parametrize("selector", [None, "", "0", "-1", "3", "1.0", "x", " 2", "01"])
@pytest.mark.parametrize("existing", [False, True])
def test_bad_or_missing_selector_stops_status_and_push_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    selector: str | None,
    existing: bool,
) -> None:
    path, defaults = source(tmp_path)
    attr = f' gorak_style="{selector}"' if selector is not None else ""
    path.with_suffix(".wml").write_text(
        f'<frame><topform><tablefield name="items"{attr}/></topform></frame>'
    )
    with pytest.raises(ProjectError, match="gorak_style"):
        decode_component(path)
    snapshot = document([new_application(path.parent), native(defaults)])
    if existing:
        cache = tmp_path / ".openroad/example"
        cache.mkdir(parents=True)
        (cache / "example.xml").write_bytes(snapshot)
        save_binding(OpenRoadConnection("local", "node", "source", None), tmp_path)
    for module in (export, sync_plan, push):
        monkeypatch.setattr(
            module,
            "read_applications",
            lambda *a: [Application("example", "", "")] if existing else [],
        )
        monkeypatch.setattr(
            module, "backup_application_xml", lambda c, a, p: p.write_bytes(snapshot)
        )
    writes: list[object] = []
    monkeypatch.setattr(push, "import_component_xml", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(
        importer, "import_component_xml", lambda *a, **k: writes.append(a)
    )
    monkeypatch.chdir(tmp_path)
    cli.main(["status"])
    plan = json.loads(capsys.readouterr().out)
    assert any(
        c["disk"] == "invalid" and "gorak_style" in c["reason"] for c in plan["changes"]
    )
    with pytest.raises(SystemExit) as result:
        cli.main(["sync", "--push"])
    assert result.value.code == 1
    error = capsys.readouterr().err
    assert "before writes" in error and "gorak_style" in error and "items" in error
    assert writes == []


@pytest.mark.parametrize("corrupt", [False, True])
def test_existing_component_import_consumes_selector_and_verifies_properties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corrupt: bool
) -> None:
    path, defaults = source(tmp_path)
    baseline = native(defaults)
    baseline.find("topform/childfields/row/fgcolor").text = "2"
    baseline.find("topform/childfields/row/hasheaderbuttons").text = "1"
    cache = tmp_path / ".openroad/example"
    cache.mkdir(parents=True)
    baseline_bytes = document([baseline])
    (cache / "panel.xml").write_bytes(baseline_bytes)
    write_projection(path, native(defaults))
    uploaded: list[bytes] = []

    def importing(c: Any, a: str, n: str, xml: Path, log: Path) -> None:
        rebuilt = etree.parse(str(xml)).find("COMPONENT")
        assert properties(rebuilt) == ("5", "0")
        uploaded.append(xml.read_bytes())

    def backup(c: Any, a: str, n: str, xml: Path) -> None:
        data = uploaded[-1] if uploaded else baseline_bytes
        if corrupt and uploaded:
            tree = etree.fromstring(data)
            tree.find("COMPONENT/topform/childfields/row/hasheaderbuttons").text = "1"
            data = etree.tostring(tree)
        xml.write_bytes(data)

    monkeypatch.setattr(importer, "import_component_xml", importing)
    monkeypatch.setattr(importer, "backup_component_xml", backup)
    connection = OpenRoadConnection("local", "node", "source", None)
    if corrupt:
        with pytest.raises(ProjectError, match="Post-import verification failed"):
            importer.import_component(connection, tmp_path, "example", "panel")
        assert (cache / "panel.xml").read_bytes() == baseline_bytes
    else:
        importer.import_component(connection, tmp_path, "example", "panel")
        assert properties(etree.parse(str(cache / "panel.xml")).find("COMPONENT")) == (
            "5",
            "0",
        )


def test_verification_checks_values_even_when_projection_is_identical(
    tmp_path: Path,
) -> None:
    _, defaults = source(tmp_path)
    defaults["field_styles"] = defaults["field_styles"][2:]
    full = native(defaults)
    missing = deepcopy(full)
    field = missing.find("topform/childfields/row")
    field.remove(field.find("fgcolor"))
    assert parse_component_node(full) == parse_component_node(missing)
    assert not equivalent(full, missing)

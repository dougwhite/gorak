"""Native stylesheet identity and explicit source state, without a database."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from gorak import native_styles as styles
from gorak.component_defaults import encode_source_w4gl, write_component_defaults
from gorak.contract_source import decode_component
from gorak.errors import ProjectError
from gorak.export import apply_field_default_inheritance
from gorak.importer import signature
from gorak.parser import parse_component_node
from gorak.style_commands import maintain, migrate

XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"


def stylesheet() -> dict[str, Any]:
    return styles.encode(
        etree.fromstring(
            '<fielddefaults xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<row xsi:type="matrixfield"><clienttext>entryfield</clienttext>'
            '<childfields><row xsi:type="entryfield"><width>0</width><fieldstyle>0</fieldstyle>'
            "<defaultstring/><script> a\n b </script><image><obj_encoded>inline</obj_encoded></image>"
            '</row><row xsi:type="entryfield"><width>0</width></row></childfields></row>'
            '<row xsi:type="matrixfield"><clienttext>entryfield</clienttext>'
            '<childfields><row xsi:type="entryfield"><width>0</width></row></childfields></row>'
            "</fielddefaults>"
        )
    )


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def export(root: Path, name: str = "panel") -> Path:
    folder = root / "example"
    folder.mkdir(exist_ok=True)
    write(folder / "app.json", {})
    node = etree.parse("tests/fixtures/fm_example_frame.xml").find("COMPONENT")
    assert node is not None
    node.set("name", name)
    old = node.find("fielddefaults")
    assert old is not None
    node.replace(old, styles.decode(stylesheet()))
    field = node.find("topform/childfields/row")
    assert field is not None
    for tag, text in [("fieldstyle", "0"), ("xleft", "0"), ("width", "0")]:
        child = field.find(tag)
        if child is None:
            child = etree.SubElement(field, tag)
        child.text = text
    component = parse_component_node(node)
    apply_field_default_inheritance(root, "example", [component], source_nodes=[node])
    source = folder / f"{name}.w4gl"
    source.write_text(encode_source_w4gl(component))
    source.with_suffix(".wml").write_text(component.markup or "")
    write_component_defaults(source, component.props["fielddefaults"])
    return source


def test_stock_baseline_retains_native_structure_and_payloads() -> None:
    value = styles.baseline()
    node = styles.decode(value)
    assert len(node.findall("row")) == 30
    rows = node.findall("row/childfields/row")
    assert len(rows) == 34
    assert len({row.get(XSI) for row in rows}) == 29
    assert (
        len(
            [
                row
                for row in node.findall("row")
                if row.findtext("clienttext") == "entryfield"
            ]
        )
        == 2
    )
    assert len(node.findall(".//obj_encoded")) == 7
    assert len(node.findall(".//script")) == 10
    assert styles.encode(node) == value
    assert signature(styles.decode(styles.encode(node))) == signature(node)
    entries = styles.entries(value)
    assert [
        (e["group_ordinal"], e["style_ordinal"])
        for e in entries
        if e["type"] == "entryfield"
    ] == [(1, 1), (2, 1)]
    assert [
        (e["group_ordinal"], e["style_ordinal"])
        for e in entries
        if e["type"] == "stackfield"
    ] == [(1, 1), (1, 2)]


@pytest.mark.parametrize(
    "operation", ["add", "remove", "reorder", "duplicate", "zero", "empty", "script"]
)
def test_exact_structural_delta_roundtrip(operation: str) -> None:
    parent = stylesheet()
    node = styles.decode(parent)
    if operation == "add":
        node.append(deepcopy(node[0]))
    elif operation == "remove":
        node.remove(node[0])
    elif operation == "reorder":
        node[:] = list(reversed(node))
    elif operation == "duplicate":
        children = node.find("row/childfields")
        assert children is not None
        children.append(deepcopy(children[0]))
    else:
        field = node.find("row/childfields/row")
        assert field is not None
        key = {"zero": "fieldstyle", "empty": "defaultstring", "script": "script"}[
            operation
        ]
        child = field.find(key)
        assert child is not None
        child.text = {"zero": "2", "empty": "text", "script": "\n preserved \n"}[
            operation
        ]
    child_value = styles.encode(node)
    for _ in range(4):
        delta = styles.difference(parent, child_value)
        assert styles.resolve(parent, delta) == child_value
        child_value = styles.encode(styles.decode(styles.resolve(parent, delta)))
    assert parent == stylesheet()


def test_bad_parent_and_ambiguous_old_layers_fail_closed() -> None:
    parent = stylesheet()
    child = deepcopy(parent)
    child["children"][0]["children"][0]["text"] = "renamed"
    delta = styles.difference(parent, child)
    changed = deepcopy(parent)
    changed["children"].reverse()
    with pytest.raises(ProjectError, match="parent structure"):
        styles.resolve(changed, delta)
    with pytest.raises(ProjectError, match="Legacy"):
        styles.resolve(parent, {"field_styles": []})


def test_explicit_fields_and_exact_stylesheet_from_source_only(tmp_path: Path) -> None:
    source = export(tmp_path)
    assert not (source.parent / "field_defaults.json").exists()
    markup = source.with_suffix(".wml").read_text()
    assert (
        'fieldstyle="0"' in markup and 'xleft="0"' in markup and 'width="0"' in markup
    )
    assert "gorak_style" not in markup
    node = decode_component(source)
    assert styles.encode(node.find("fielddefaults")) == stylesheet()
    before = signature(node.find("topform"))
    write(source.with_suffix(".fielddefaults.json"), styles.complete(styles.baseline()))
    assert signature(decode_component(source).find("topform")) == before
    assert not (tmp_path / ".openroad").exists()


def test_native_fieldstyle_omission_and_ordinals(tmp_path: Path) -> None:
    source = export(tmp_path)
    for value in [None, "0", "1", "2", "9"]:
        attr = "" if value is None else f' fieldstyle="{value}"'
        source.with_suffix(".wml").write_text(
            f'<frame><topform><entryfield name="value"{attr}/></topform></frame>'
        )
        node = decode_component(source)
        assert node.findtext("topform/childfields/row/fieldstyle") == value
    source.with_suffix(".wml").write_text('<frame><topform gorak_style="1"/></frame>')
    with pytest.raises(ProjectError, match="gorak_style"):
        decode_component(source)


def test_publish_and_compact_preserve_every_frame_and_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = export(tmp_path, "one")
    second = export(tmp_path, "two")
    before = {p: styles.frame_styles(p) for p in (first, second)}
    original = first.with_suffix(".wml").read_bytes()
    plan = maintain(tmp_path, "compact", dry_run=True)
    assert "Remove example/one.fielddefaults.json" in plan
    assert first.with_suffix(".fielddefaults.json").exists()
    maintain(tmp_path, "compact")
    assert {p: styles.frame_styles(p) for p in before} == before
    assert not first.with_suffix(".fielddefaults.json").exists()
    assert maintain(tmp_path, "compact") == "Stylesheets unchanged"
    maintain(tmp_path, "publish")
    monkeypatch.setattr(
        styles, "baseline", lambda: pytest.fail("Published source consulted baseline")
    )
    assert {p: styles.frame_styles(p) for p in before} == before
    assert maintain(tmp_path, "publish") == "Stylesheets unchanged"
    assert first.with_suffix(".wml").read_bytes() == original


def test_migration_without_native_evidence_does_not_write(tmp_path: Path) -> None:
    write(tmp_path / "field_defaults.json", {})
    write(tmp_path / "app/app.json", {})
    source = tmp_path / "app/panel.w4gl"
    source.write_text("[framesource]\n")
    source.with_suffix(".wml").write_text("<frame><topform/></frame>")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ProjectError, match="Authoritative native XML"):
        migrate(tmp_path)
    assert {p: p.read_bytes() for p in before} == before


def test_migrate_authoritative_legacy_and_repeat(tmp_path: Path) -> None:
    from gorak.xml_writer import document

    folder = tmp_path / "example"
    folder.mkdir()
    write(folder / "app.json", {})
    write(tmp_path / "field_defaults.json", {"field_styles": []})
    source = folder / "panel.w4gl"
    source.write_text('[framesource]\nwindowtitle="Panel"\n')
    source.with_suffix(".wml").write_text(
        '<frame><topform><entryfield name="input" xleft="0" fieldstyle="0"/></topform></frame>'
    )
    native = decode_component(source)
    assert native.find("fielddefaults") is not None
    cache = tmp_path / ".openroad/example/panel.xml"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(document([native]))
    before = source.read_bytes()
    migrate(tmp_path, dry_run=True)
    assert source.read_bytes() == before
    migrate(tmp_path)
    assert styles.is_native_source(source)
    assert signature(decode_component(source)) == signature(native)
    assert migrate(tmp_path) == "Stylesheets unchanged"
    assert list((tmp_path / ".openroad/styles").glob("*/before/example/panel.w4gl"))


def test_native_verification_detects_wrapper_and_field_drift(tmp_path: Path) -> None:
    from gorak.contract_source import equivalent

    source = export(tmp_path)
    node = decode_component(source)
    changed = deepcopy(node)
    row = changed.find("fielddefaults/row")
    assert row is not None
    etree.SubElement(row, "width").text = "999"
    assert not equivalent(node, changed, exact_styles=True)
    changed = deepcopy(node)
    style = changed.find("topform/childfields/row/fieldstyle")
    assert style is not None
    style.getparent().remove(style)
    assert not equivalent(node, changed, exact_styles=True)


def test_explicit_wml_preserves_whitespace_and_invalid_character_text() -> None:
    from gorak.parser import encode_frame_markup
    from gorak.wml_writer import parse_markup

    node = etree.fromstring(
        '<topform><childfields><row xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="entryfield"><defaultstring>  a<?ingres_invalidxmlchar 7?>b  </defaultstring><script>\n on entry = {}\n </script></row></childfields></topform>'
    )
    markup = parse_markup(encode_frame_markup([node], explicit=True))
    from gorak.xml_text import text_value

    assert text_value(markup.find("topform/entryfield/defaultstring")) == "  a\x07b  "
    assert text_value(markup.find("topform/entryfield/script")) == "\n on entry = {}\n "


def test_publish_retains_project_customisation_and_inherited_stock(
    tmp_path: Path,
) -> None:
    stock = styles.baseline()
    node = styles.decode(stock)
    width = node.find("row/childfields/row/width")
    assert width is not None
    width.text = "0"
    project = styles.encode(node)
    write(tmp_path / "field_defaults.json", styles.difference(stock, project))
    maintain(tmp_path, "publish")
    published = styles.read(tmp_path / "field_defaults.json")
    assert published["mode"] == "complete"
    assert styles.resolve(None, published) == project
    assert len(styles.entries(styles.resolve(None, published))) == 34


@pytest.mark.parametrize(
    "marker", ["push-pending.json", "pull-pending.json", "revision-quarantine.json"]
)
def test_styles_maintenance_retains_pending_state(tmp_path: Path, marker: str) -> None:
    write(tmp_path / "field_defaults.json", styles.empty_delta())
    write(tmp_path / ".openroad" / marker, {})
    before = (tmp_path / "field_defaults.json").read_bytes()
    with pytest.raises(ProjectError):
        maintain(tmp_path, "publish")
    assert (tmp_path / ".openroad" / marker).exists()
    assert (tmp_path / "field_defaults.json").read_bytes() == before


def test_styles_maintenance_keeps_recovery_marker_on_failed_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import style_commands

    write(tmp_path / "field_defaults.json", styles.empty_delta())
    before = (tmp_path / "field_defaults.json").read_bytes()

    def fail(*args: Any) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(style_commands, "apply_files", fail)
    with pytest.raises(OSError, match="simulated"):
        maintain(tmp_path, "publish")
    assert (tmp_path / ".openroad/pull-pending.json").exists()
    assert (tmp_path / "field_defaults.json").read_bytes() == before


def test_designer_json_command_and_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak import cli

    source = export(tmp_path)
    write(tmp_path / "gorak.json", {"name": "example"})
    monkeypatch.chdir(tmp_path)
    cli.main(["styles", "show", "--app", "example", "--component", source.stem])
    data = json.loads(capsys.readouterr().out)
    assert data["stylesheet"] == styles.frame_styles(source)
    assert len(data["entries"]) == 3
    assert not (tmp_path / ".openroad").exists()
    cli.main(["styles", "publish", "--dry-run"])
    assert "Write field_defaults.json" in capsys.readouterr().out
    assert styles.read(tmp_path / "field_defaults.json")["mode"] == "delta"
    with pytest.raises(SystemExit) as result:
        cli.main(["styles", "show", "--component", source.stem])
    assert result.value.code == 1
    assert "requires --app" in capsys.readouterr().err

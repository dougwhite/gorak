"""The component JSON layer participates in export, reconstruction and sync."""

import json
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from gorak import export, importer, sync_plan
from gorak.component_defaults import defaults_path, write_component_defaults
from gorak.connection import OpenRoadConnection
from gorak.contract_source import decode_component
from gorak.domain import Application
from gorak.errors import ProjectError
from gorak.field_defaults import flatten_app_defaults
from gorak.importer import signature
from gorak.source_migration import migrate_source
from gorak.xml_writer import document

CONNECTION = OpenRoadConnection("local", "node", "db", None)


def style(**values: str) -> dict[str, Any]:
    return {
        "field_styles": [
            {"type": "buttonfield", "group": "buttonfield", "properties": values}
        ]
    }


def project(root: Path) -> Path:
    (root / "gorak.json").write_text('{"name":"example"}')
    (root / "field_defaults.json").write_text(
        json.dumps(
            {
                **style(bgcolor="2", width="100"),
                "common_model_container": {"type": "matrixfield", "properties": {}},
            }
        )
    )
    folder = root / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    (folder / "field_defaults.json").write_text(json.dumps(style(bgcolor="3")))
    path = folder / "panel.w4gl"
    path.write_text('[framesource]\nwindowtitle="Panel"\n===\ninitialize()={}\n')
    path.with_suffix(".wml").write_text(
        '<frame><topform><buttonfield name="go"/></topform></frame>'
    )
    return path


def test_component_json_resolves_root_app_and_frame_and_removes_empty(
    tmp_path: Path,
) -> None:
    path = project(tmp_path)
    write_component_defaults(path, style(bgcolor="3", width="150"))
    assert json.loads(defaults_path(path).read_text()) == style(width="150")
    control = decode_component(path).find("topform/childfields/row")
    assert control is not None
    assert control.findtext("bgcolor") == "3"
    assert control.findtext("width") == "150"
    path.with_suffix(".wml").write_text(
        '<frame><topform><buttonfield name="go" width="175"/></topform></frame>'
    )
    assert decode_component(path).findtext("topform/childfields/row/width") == "175"
    write_component_defaults(path, style(bgcolor="3", width="100"))
    assert not defaults_path(path).exists()


@pytest.mark.parametrize("content", ["[]", "null", "{broken"])
def test_invalid_component_defaults_fail_closed(tmp_path: Path, content: str) -> None:
    path = project(tmp_path)
    defaults_path(path).write_text(content)
    with pytest.raises(
        ProjectError, match="component field defaults|Component field defaults"
    ):
        decode_component(path)


def test_legacy_inline_defaults_still_work_but_cannot_compete_with_json(
    tmp_path: Path,
) -> None:
    path = project(tmp_path)
    path.write_text(
        path.read_text().replace(
            "===",
            '[fielddefaults.common_model_container.properties]\nbgcolor="4"\n===',
            1,
        )
    )
    assert decode_component(path).findtext("fielddefaults/row/bgcolor") == "4"
    defaults_path(path).write_text("{}")
    with pytest.raises(ProjectError, match="both TOML"):
        decode_component(path)


def test_export_writes_only_delta_and_cleans_stale_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = project(tmp_path)
    defaults_path(path).write_text(json.dumps(style(width="150")))
    node = decode_component(path)
    xml = document([node])
    monkeypatch.setattr(
        export, "backup_component_xml", lambda c, a, n, p: p.write_bytes(xml)
    )
    paths = export.ComponentExportPaths(tmp_path / "panel.xml", path)
    export.export_component_to_paths(CONNECTION, "example", "panel", paths)
    assert "fielddefaults" not in path.read_text()
    assert json.loads(defaults_path(path).read_text()) == style(width="150")
    assert signature(decode_component(path)) == signature(node)
    defaults_path(path).unlink()
    xml = document([decode_component(path)])
    defaults_path(path).write_text(json.dumps(style(width="999")))
    export.export_component_to_paths(CONNECTION, "example", "panel", paths)
    assert not defaults_path(path).exists()


def test_application_export_uses_component_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = project(tmp_path)
    defaults_path(path).write_text(json.dumps(style(width="150")))
    node = decode_component(path)
    app = etree.Element("APPLICATION", name="example")
    xml = document([app, node])
    monkeypatch.setattr(
        export, "backup_application_xml", lambda c, a, p: p.write_bytes(xml)
    )
    export.export_application_to_paths(
        CONNECTION,
        "example",
        export.ApplicationExportPaths(tmp_path / "export.xml", path.parent),
        None,
    )
    assert "fielddefaults" not in path.read_text()
    assert json.loads(defaults_path(path).read_text()) == style(width="150")
    assert signature(decode_component(path)) == signature(node)


def test_flatten_preserves_effective_frame_and_prunes_redundant_values(
    tmp_path: Path,
) -> None:
    path = project(tmp_path)
    defaults_path(path).write_text(json.dumps(style(bgcolor="3", width="150")))
    before = signature(decode_component(path))
    flatten_app_defaults(tmp_path)
    assert signature(decode_component(path)) == before
    assert json.loads(defaults_path(path).read_text()) == style(width="150")
    defaults_path(path).write_text(json.dumps(style(bgcolor="3", width="100")))
    flatten_app_defaults(tmp_path)
    assert not defaults_path(path).exists()


def test_migration_moves_inline_defaults_and_preserves_reconstruction(
    tmp_path: Path,
) -> None:
    path = project(tmp_path)
    path.write_text(
        path.read_text().replace(
            "===",
            '[[fielddefaults.field_styles]]\ntype="buttonfield"\ngroup="buttonfield"\n[fielddefaults.field_styles.properties]\nwidth="150"\n===',
            1,
        )
    )
    before = signature(decode_component(path))
    operation = migrate_source(tmp_path)
    assert operation is not None
    assert "fielddefaults" not in path.read_text()
    assert json.loads(defaults_path(path).read_text()) == style(width="150")
    assert signature(decode_component(path)) == before
    assert migrate_source(tmp_path) is None


def test_status_detects_sidecar_only_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = project(tmp_path)
    xml = document(
        [etree.Element("APPLICATION", name="example"), decode_component(path)]
    )
    cache = tmp_path / ".openroad/example/example.xml"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(xml)
    monkeypatch.setattr(
        sync_plan, "read_applications", lambda c: [Application("example", "", "")]
    )
    monkeypatch.setattr(
        sync_plan, "backup_application_xml", lambda c, a, p: p.write_bytes(xml)
    )
    defaults_path(path).write_text(json.dumps(style(width="150")))
    changes = sync_plan.plan_project(CONNECTION, tmp_path)
    assert next(c for c in changes if c.key == "example/panel").action == "push"


def test_import_rejects_concurrent_sidecar_change_and_retains_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = project(tmp_path)
    xml = document([decode_component(path)])
    cache = tmp_path / ".openroad/example/panel.xml"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(xml)
    defaults_path(path).write_text(json.dumps(style(width="150")))

    def backup(c: Any, a: str, n: str, p: Path) -> None:
        p.write_bytes(xml)
        defaults_path(path).write_text(json.dumps(style(width="175")))

    monkeypatch.setattr(importer, "backup_component_xml", backup)

    def forbidden(*args: Any) -> None:
        pytest.fail("must not import concurrently changed source")

    monkeypatch.setattr(importer, "import_component_xml", forbidden)
    with pytest.raises(ProjectError, match="Local source changed"):
        importer.import_component(CONNECTION, tmp_path, "example", "panel")
    copies = list((tmp_path / ".openroad/imports").glob("*/source.fielddefaults.json"))
    assert len(copies) == 1
    assert json.loads(copies[0].read_text()) == style(width="150")


def test_component_delta_does_not_copy_other_parent_styles(tmp_path: Path) -> None:
    path = project(tmp_path)
    parent_path = tmp_path / "field_defaults.json"
    parent = json.loads(parent_path.read_text())
    parent["field_styles"].append(
        {"type": "entryfield", "group": "entryfield", "properties": {"width": "200"}}
    )
    parent_path.write_text(json.dumps(parent))
    write_component_defaults(path, style(bgcolor="3", width="150"))
    assert json.loads(defaults_path(path).read_text()) == style(width="150")


def test_duplicate_style_identity_keeps_selector_alignment(tmp_path: Path) -> None:
    path = project(tmp_path)
    parent_path = tmp_path / "field_defaults.json"
    parent = json.loads(parent_path.read_text())
    parent["field_styles"].append(
        {
            "type": "buttonfield",
            "group": "buttonfield",
            "properties": {"width": "200", "bgcolor": "2"},
        }
    )
    parent_path.write_text(json.dumps(parent))
    overrides = {
        "field_styles": [
            style(bgcolor="3", width="100")["field_styles"][0],
            style(bgcolor="2", width="250")["field_styles"][0],
        ]
    }
    defaults_path(path).write_text(json.dumps(overrides))
    path.with_suffix(".wml").write_text(
        '<frame><topform><buttonfield name="go" gorak_style="2"/></topform></frame>'
    )
    before = signature(decode_component(path))
    write_component_defaults(path, overrides)
    delta = json.loads(defaults_path(path).read_text())
    assert delta["field_styles"][0]["properties"] == {}
    assert delta["field_styles"][1]["properties"] == {"width": "250"}
    assert signature(decode_component(path)) == before
    assert decode_component(path).findtext("topform/childfields/row/width") == "250"


@pytest.mark.parametrize("kind", ["framesource", "frametemplate", "futuretype"])
def test_defaults_only_migration_preserves_opaque_source_and_layout(
    tmp_path: Path, kind: str
) -> None:
    path = project(tmp_path)
    script = b"===\r\n\r\n// text\x07after character\r\n  RETURN 1;\n\n"
    path.write_bytes(
        (
            "["
            + kind
            + ']\nwindowtitle="Example"\n[[fielddefaults.field_styles]]\ntype="buttonfield"\ngroup="buttonfield"\n[fielddefaults.field_styles.properties]\nwidth="150"\n\n'
        ).encode()
        + script
    )
    # A malformed/unsupported layout is irrelevant to a metadata-only move.
    path.with_suffix(".wml").write_bytes(b"<unknown-layout>opaque")
    untouched = {
        p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file() and p != path
    }
    before = path.read_bytes()
    operation = migrate_source(tmp_path, field_defaults_only=True)
    assert operation is not None
    assert path.read_bytes().endswith(script)
    assert b"fielddefaults" not in path.read_bytes()
    assert json.loads(defaults_path(path).read_text()) == style(width="150")
    assert all(p.read_bytes() == content for p, content in untouched.items())
    assert (operation / "before/example/panel.w4gl").read_bytes() == before
    assert migrate_source(tmp_path, field_defaults_only=True) is None


def test_defaults_only_migration_refuses_competing_definitions_without_writes(
    tmp_path: Path,
) -> None:
    path = project(tmp_path)
    path.write_text(
        path.read_text().replace(
            "===", '[fielddefaults.common_model_container.properties]\nbgcolor="4"\n==='
        )
    )
    defaults_path(path).write_text("{}")
    original = path.read_bytes()
    with pytest.raises(ProjectError, match="both TOML"):
        migrate_source(tmp_path, field_defaults_only=True)
    assert path.read_bytes() == original
    assert defaults_path(path).read_text() == "{}"


def test_defaults_only_migration_checks_concurrent_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import defaults_migration

    path = project(tmp_path)
    defaults_path(path).write_text(json.dumps(style(width="150")))
    from gorak.component_defaults import minimal_component_defaults

    original = minimal_component_defaults

    def concurrent(source: Path, values: dict[str, Any]) -> dict[str, Any]:
        result = original(source, values)
        source.write_bytes(source.read_bytes() + b"\n// concurrent edit\n")
        return result

    monkeypatch.setattr(defaults_migration, "minimal_component_defaults", concurrent)
    with pytest.raises(ProjectError, match="Source changed"):
        migrate_source(tmp_path, field_defaults_only=True)
    assert path.read_bytes().endswith(b"// concurrent edit\n")

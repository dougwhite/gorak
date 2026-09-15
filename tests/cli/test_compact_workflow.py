"""ORAPI-era source exercises the CLI without preview codecs or XML companions."""

import json
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from gorak import cli, export, push, readable_source, sync_plan
from gorak.domain import Application
from gorak.run_backend import RunResult


def test_untouched_compact_project_cli_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Synthetic, checked-in contract spellings; do not generate the input with
    # today's exporter, which would hide a source-format regression.
    folder = tmp_path / "example"
    folder.mkdir()
    (tmp_path / "gorak.json").write_text('{"name":"example","tests":["example"]}\n')
    (tmp_path / ".env").write_text(
        "GORAK_BACKEND=local\nGORAK_VNODE=node\nGORAK_DATABASE=source\n"
    )
    (folder / "app.json").write_text(
        '{\n    "starting_component": "panel",\n    "description": "",\n'
        '    "included_applications": []\n}\n'
    )
    (tmp_path / "field_defaults.json").write_text(
        '{"common_model_container":{"type":"matrixfield","properties":{"bgcolor":"2"}},'
        '"field_styles":[{"type":"buttonfield","group":"buttonfield","properties":{"bgcolor":"2"}}]}\n'
    )
    (folder / "field_defaults.json").write_text("{}\n")
    (folder / "panel.w4gl").write_text(
        '[framesource]\nwindowtitle = "Example"\n\n===\n\ninitialize()={}'
    )
    (folder / "panel.wml").write_text(
        '<frame>\n  <topform>\n    <buttonfield name="go" textlabel="Go"/>\n'
        "  </topform>\n</frame>\n"
    )
    (folder / "widget.w4gl").write_text(
        '[classsource]\nsuperclass = "userobject"\n\n[attributes]\n'
        'count = "INTEGER NOT NULL"\n\n[methods]\n'
        'get_count = "METHOD RETURNING INTEGER NOT NULL"\n\n===\n\n'
        "method get_count()={return CurObject.count;}"
    )
    sources = [p for p in tmp_path.rglob("*") if p.is_file() and p.name != ".env"]
    before = {p: p.read_bytes() for p in sources}
    assert not list(tmp_path.rglob("*.xml"))
    assert all(
        b"source_format" not in b and b"defaults_inherited" not in b
        for b in before.values()
    )
    monkeypatch.chdir(tmp_path)

    def preview_forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Ordinary compact workflow must not invoke preview codecs")

    for name in (
        "encode_component",
        "decode_component",
        "encode_application",
        "decode_application",
    ):
        monkeypatch.setattr(readable_source, name, preview_forbidden)

    database: list[bytes] = []
    imports: list[str] = []

    def applications(*args: Any) -> list[Application]:
        return [Application("example", "panel", "")] if database else []

    def backup(connection: Any, app: str, path: Path) -> None:
        assert app == "example" and database
        path.write_bytes(database[0])

    def importing(
        connection: Any, app: str, component: str, xml: Path, log: Path, *, create: bool
    ) -> None:
        assert create and component == "-" and not database
        database.append(xml.read_bytes())
        imports.append(app)
        # Inherited value was restored without requiring it in WML.
        tree = etree.fromstring(database[0])
        assert tree.findtext("COMPONENT[@name='panel']/topform/bgcolor") == "2"

    for module in (export, push, sync_plan):
        monkeypatch.setattr(module, "read_applications", applications)
        monkeypatch.setattr(module, "backup_application_xml", backup)
    monkeypatch.setattr(push, "import_component_xml", importing)
    monkeypatch.setattr(export, "read_component_sync_metadata", lambda *a: [])

    def run(*args: Any) -> RunResult:
        assert imports == ["example"], "Tests must run after the real push pipeline"
        return RunResult(
            0,
            False,
            "",
            '<testsuite tests="1"><testcase name="works"/></testsuite>',
            "trace",
        )

    monkeypatch.setattr(cli, "execute_application", run)
    cli.main(["status"])
    assert json.loads(capsys.readouterr().out)["changes"]
    cli.main(["sync", "--push"])
    assert imports == ["example"]
    capsys.readouterr()
    with pytest.raises(SystemExit) as result:
        cli.main(["test"])
    assert result.value.code == 0
    assert "Tests: 1, failures: 0, errors: 0" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in sources} == before
    for _ in range(2):
        cli.main(["app", "export", "example"])
        capsys.readouterr()
        assert {p: p.read_bytes() for p in sources} == before
        cli.main(["status"])
        assert json.loads(capsys.readouterr().out)["changes"] == []
        cli.main(["sync", "--push"])
        capsys.readouterr()
        assert imports == ["example"]
    assert not list(folder.rglob("*.xml"))
    assert {
        p
        for p in tmp_path.rglob("*")
        if p.is_file() and p.name != ".env" and ".openroad" not in p.parts
    } == set(sources)

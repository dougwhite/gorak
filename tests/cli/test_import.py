from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak.connection import OpenRoadConnection


def test_import_cli_resolves_project_and_dry_run(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    (tmp_path / "gorak.json").write_text('{"name": "demo"}')
    monkeypatch.chdir(tmp_path)
    calls: list[object] = []

    def run(
        connection: OpenRoadConnection,
        root: Path,
        app: str,
        component: str,
        dry_run: bool,
    ) -> Path:
        calls.append((connection.database, root, app, component, dry_run))
        return root / ".openroad/imports/example"

    monkeypatch.setattr(cli, "import_component", run)
    cli.main(
        [
            "component",
            "import",
            "app",
            "example",
            "--backend",
            "local",
            "--vnode",
            "node",
            "--database",
            "demo",
            "--dry-run",
        ]
    )
    assert calls == [("demo", tmp_path, "app", "example", True)]
    assert "Import preview prepared" in capsys.readouterr().out


def test_import_cli_requires_project(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="1"):
        cli.main(["component", "import", "app", "example"])
    assert "Import requires a gorak project" in capsys.readouterr().err


def test_malformed_import_source_reports_friendly_error_before_backend_calls(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    from gorak import importer

    (tmp_path / "gorak.json").write_text('{"name":"demo"}')
    folder = tmp_path / "app"
    folder.mkdir()
    (folder / "example.w4gl").write_text(
        '[proc4glsource]\ndatatype = "unterminated\n===\nRETURN;'
    )
    cache = tmp_path / ".openroad/app"
    cache.mkdir(parents=True)
    (cache / "example.xml").write_text(
        '<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><COMPONENT name="example" xsi:type="proc4glsource"><datatype>integer</datatype><script>RETURN 0;</script></COMPONENT></OPENROAD>'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        importer,
        "backup_component_xml",
        lambda *a: pytest.fail("must not contact backend"),
    )
    with pytest.raises(SystemExit, match="1"):
        cli.main(
            [
                "component",
                "import",
                "app",
                "example",
                "--backend",
                "local",
                "--vnode",
                "node",
                "--database",
                "demo",
            ]
        )
    output = capsys.readouterr().err
    assert "Cannot validate import source" in output
    assert "example.w4gl" in output
    assert "Traceback" not in output
    assert not (tmp_path / ".openroad/imports").exists()

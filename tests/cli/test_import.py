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

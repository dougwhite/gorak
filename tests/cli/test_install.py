from pathlib import Path

import pytest

from gorak import cli
from gorak.installation import installation_sql


def test_export_sql_works_outside_project_without_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "install.sql"
    cli.main(["install", "--export-sql", str(path)])
    assert path.read_text() == installation_sql()
    assert "no database changes" in capsys.readouterr().out
    assert sorted(p.name for p in tmp_path.iterdir()) == ["install.sql"]


def test_stdout_contains_only_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    cli.main(["install", "--export-sql", "-"])
    assert capsys.readouterr().out == installation_sql()
    assert not list(tmp_path.iterdir())

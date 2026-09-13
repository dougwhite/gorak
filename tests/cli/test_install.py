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


@pytest.mark.parametrize("issues,code", [([], 0), (["Missing rule"], 1)])
def test_check_outputs_json_and_exit_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    issues: list[str],
    code: int,
) -> None:
    import json

    from gorak import connection, installation_check
    from gorak.installation_check import InstallationCheck

    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *args: None)
    monkeypatch.setattr(connection, "require_odbc_settings", lambda *args: None)
    monkeypatch.setattr(
        installation_check,
        "check_installation",
        lambda *args: InstallationCheck(
            "incomplete" if issues else "capture_only_inventory_present", None, issues
        ),
    )
    with pytest.raises(SystemExit) as caught:
        cli.main(["install", "--check"])
    assert caught.value.code == code
    assert json.loads(capsys.readouterr().out)["issues"] == issues


def test_install_actions_are_exclusive() -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["install", "--check", "--export-sql", "-"])
    assert caught.value.code == 2

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


def test_upgrade_sql_can_be_exported_without_connection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.main(["install", "--upgrade", "--export-sql", "-"])
    sql = capsys.readouterr().out
    assert "Upgrade v1 to v2 only" in sql
    assert "create table gorak_journal_acks" in sql
    assert "create rule gorak_track_" not in sql


def test_revision_export_without_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak.revision_installation import revision_installation_sql

    monkeypatch.chdir(tmp_path)
    cli.main(["install", "--export-revision-sql", "-"])
    assert capsys.readouterr().out == revision_installation_sql()
    path = tmp_path / "revisions.sql"
    cli.main(["install", "--export-revision-sql", str(path)])
    assert path.read_text() == revision_installation_sql()
    assert "no database changes" in capsys.readouterr().out


@pytest.mark.parametrize("option", ["--check", "--upgrade"])
def test_revision_export_rejects_other_install_modes(option: str) -> None:
    with pytest.raises(SystemExit):
        cli.main(["install", "--export-revision-sql", "-", option])


@pytest.mark.parametrize("issues,code", [([], 0), (["Missing revision rule"], 1)])
def test_revision_check_outputs_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    issues: list[str],
    code: int,
) -> None:
    import json

    from gorak import connection, revision_check

    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *args: None)
    monkeypatch.setattr(connection, "require_odbc_settings", lambda *args: None)
    monkeypatch.setattr(
        revision_check,
        "check_revision_installation",
        lambda *args: revision_check.RevisionCheck(
            "incomplete" if issues else "revision_structure_verified", issues
        ),
    )
    with pytest.raises(SystemExit) as caught:
        cli.main(["install", "--check-revision"])
    assert caught.value.code == code
    report = json.loads(capsys.readouterr().out)
    assert report["issues"] == issues
    assert report["incremental_ready"] is False


@pytest.mark.parametrize(
    "option", ["--check", "--upgrade", "--export-sql", "--export-revision-sql"]
)
def test_revision_check_rejects_other_actions(option: str) -> None:
    with pytest.raises(SystemExit):
        cli.main(["install", "--check-revision", option])


def test_offline_revision_reset_export_is_explicit_and_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak.revision_installation import revision_reset_sql

    monkeypatch.chdir(tmp_path)
    cli.main(["install", "--export-revision-reset-sql", "-"])
    assert capsys.readouterr().out == revision_reset_sql()
    path = tmp_path / "reset.sql"
    cli.main(["install", "--export-revision-reset-sql", str(path)])
    assert path.read_text() == revision_reset_sql()
    with pytest.raises(SystemExit) as caught:
        cli.main(["install", "--export-revision-reset-sql", str(path)])
    assert caught.value.code == 1
    assert "Refusing to overwrite" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["install", "--export-revision-reset-sql", "-", "--check"])

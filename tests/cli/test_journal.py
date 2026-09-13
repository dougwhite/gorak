import json
from pathlib import Path

import pytest

from gorak import cli, connection, journal
from gorak.journal import JournalBatch


def test_preview_command_does_not_consume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "gorak.json").write_text('{"name": "journal_demo"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *a: None)
    monkeypatch.setattr(connection, "require_odbc_settings", lambda *a: None)
    limits: list[int] = []

    def poll(*args: object) -> JournalBatch:
        limits.append(int(str(args[2])))
        return JournalBatch("installation", (), 0)

    monkeypatch.setattr(journal, "poll_journal", poll)
    cli.main(["journal", "--limit", "10"])
    output = json.loads(capsys.readouterr().out)
    assert output["acknowledged"] is False
    assert output["incremental_ready"] is False
    assert limits == [10]
    assert not (tmp_path / ".openroad" / "mutation.lock").exists()


def test_journal_requires_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as error:
        cli.main(["journal"])
    assert error.value.code == 1
    assert "requires a gorak project" in capsys.readouterr().err

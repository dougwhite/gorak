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


def test_reconcile_dispatches_to_comparison_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak import journal_reconcile

    (tmp_path / "gorak.json").write_text('{"name":"journal_demo"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *a: None)
    calls: list[int] = []

    def reconcile(connection: object, root: Path, limit: int) -> dict[str, object]:
        assert root == tmp_path
        calls.append(limit)
        return {"processed_events": 2}

    monkeypatch.setattr(journal_reconcile, "reconcile_journal", reconcile)
    cli.main(["journal", "--reconcile", "--limit", "2"])
    assert json.loads(capsys.readouterr().out)["processed_events"] == 2
    assert calls == [2]


def test_map_outputs_candidates_without_acknowledging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak import journal_mapping
    from gorak.journal_mapping import ApplicationCandidates

    (tmp_path / "gorak.json").write_text('{"name":"journal_demo"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *a: None)
    monkeypatch.setattr(connection, "require_odbc_settings", lambda *a: None)
    monkeypatch.setattr(
        journal, "poll_journal", lambda *a: JournalBatch("installation", (), 0)
    )
    monkeypatch.setattr(
        journal_mapping,
        "map_applications",
        lambda *a: ApplicationCandidates(("example",), False, (), 1),
    )
    cli.main(["journal", "--map"])
    output = json.loads(capsys.readouterr().out)
    assert output["mapping"]["applications"] == ["example"]
    assert output["acknowledged"] is False
    assert output["incremental_ready"] is False


def test_selective_verification_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak import journal_snapshot

    (tmp_path / "gorak.json").write_text('{"name":"journal_demo"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *a: None)
    monkeypatch.setattr(
        journal_snapshot,
        "verify_selective_snapshot",
        lambda *a: {"mode": "selective_verified"},
    )
    cli.main(["journal", "--verify-selective"])
    assert json.loads(capsys.readouterr().out)["mode"] == "selective_verified"


def test_rebootstrap_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak import journal_snapshot

    (tmp_path / "gorak.json").write_text('{"name":"journal_demo"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *a: None)

    def run(
        connection: object, root: Path, limit: int, *, rebootstrap: bool
    ) -> dict[str, object]:
        assert root == tmp_path
        assert rebootstrap is True
        return {"rebootstrapped": True}

    monkeypatch.setattr(journal_snapshot, "verify_selective_snapshot", run)
    cli.main(["journal", "--rebootstrap"])
    assert json.loads(capsys.readouterr().out)["rebootstrapped"] is True


def test_rebootstrap_cannot_be_combined_with_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"journal_demo"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *a: None)
    with pytest.raises(SystemExit):
        cli.main(["journal", "--rebootstrap", "--reconcile"])
    assert "Choose one journal mode" in capsys.readouterr().err

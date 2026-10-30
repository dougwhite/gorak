from threading import Event

import pytest

from gorak.operation_progress import progress_scope, report


def test_progress_percentages_are_per_phase_and_silent_outside_scope() -> None:
    messages: list[str] = []
    report("Outside scope")
    with progress_scope("Status", messages.append):
        report("Local source", 1, 4)
        report("Local source", 1, 4)
        report("Local source", 4, 4)
        report("Database source", 0, 2)
    assert sum("25%" in message for message in messages) == 1
    assert any("75% of phase remaining" in message for message in messages)
    assert any("Local source: 100%" in message for message in messages)
    assert any("Database source: 0%" in message for message in messages)
    report("After scope")
    assert not any("Outside" in message or "After" in message for message in messages)


def test_heartbeat_reports_wait_and_stops_after_failure() -> None:
    heartbeat = Event()
    messages: list[str] = []

    def emit(message: str) -> None:
        messages.append(message)
        if "Still running" in message:
            heartbeat.set()

    with pytest.raises(RuntimeError, match="failed"):
        with progress_scope("Sync", emit, interval=0.01):
            report("Waiting for database export")
            assert heartbeat.wait(2)
            raise RuntimeError("failed")
    assert any(
        "Waiting for database export" in message and "Still running" in message
        for message in messages
    )
    # Scope reset allows a subsequent command to use its own reporter.
    subsequent: list[str] = []
    with progress_scope("Status", subsequent.append):
        report("New command")
    assert subsequent[-1] == "New command"


def test_default_progress_output_uses_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with progress_scope("Status"):
        report("Comparing", 1, 2)
    output = capsys.readouterr()
    assert output.out == ""
    assert "Comparing: 50%" in output.err


def test_sync_cli_enables_progress_without_changing_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak import cli

    def syncing(args: object) -> str:
        report("Local source", 1, 2)
        return "Sync complete"

    monkeypatch.setattr(cli, "sync_command", syncing)
    cli.main(["sync"])
    output = capsys.readouterr()
    assert output.out == "Sync complete\n"
    assert "Local source: 50%" in output.err

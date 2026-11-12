from pathlib import Path
from typing import Any

import pytest

from gorak import cli, transfers
from gorak.connection import OpenRoadConnection


@pytest.mark.parametrize(
    ("command", "direction"),
    [
        (["pull"], "pull"),
        (["sync"], "sync"),
        (["push"], "push"),
    ],
)
def test_transfer_directions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str], direction: str
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "resolve_openroad_connection",
        lambda *_: OpenRoadConnection("local", "node", "test", None),
    )
    calls: list[str] = []

    def run(c: Any, root: Path, **kwargs: Any) -> transfers.Result:
        assert root == tmp_path
        assert (root / ".openroad/mutation.lock").exists()
        calls.append(direction)
        return transfers.Result(direction)

    monkeypatch.setattr(transfers, "inventory", lambda *_: {})
    if direction == "sync":

        def pulling(*args: Any, **kwargs: Any) -> transfers.Result:
            calls.append("pull")
            return transfers.Result("pull")

        monkeypatch.setattr(transfers, "pull", pulling)
        monkeypatch.setattr(transfers, "push", run)
    else:
        monkeypatch.setattr(transfers, direction, run)
    cli.main(command)
    assert calls == (["pull", "sync"] if direction == "sync" else [direction])


def test_batch_failure_returns_nonzero_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "resolve_openroad_connection",
        lambda *_: OpenRoadConnection("local", "node", "test", None),
    )
    monkeypatch.setattr(transfers, "inventory", lambda *_: {})
    monkeypatch.setattr(
        transfers,
        "push",
        lambda *a, **k: transfers.Result(
            "push", ["example/good"], {"example/bad": "rejected"}
        ),
    )
    with pytest.raises(SystemExit) as error:
        cli.main(["push"])
    assert error.value.code == 1
    assert "1 succeeded, 1 failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("push", "pull", "conflicts", "output"),
    [
        (["example/a"], [], [], "Pending push (1):\n-> example/a"),
        ([], ["example/b"], [], "Pending pull (1):\n<- example/b"),
        (
            ["example/a"],
            ["example/b"],
            [],
            "Pending push (1):\n-> example/a\n\nPending pull (1):\n<- example/b",
        ),
        (
            ["example/a", "example/b"],
            ["example/a"],
            [{"local": "example/a", "database": "example/a", "reason": "Both changed"}],
            "Pending push (2):\n-> example/a\n-> example/b\n\nPending pull (1):\n<- example/a\n\nConflicts (1):\n!! example/a (Both changed)",
        ),
    ],
)
def test_status_prints_greppable_direction_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    push: list[str],
    pull: list[str],
    conflicts: list[dict[str, str]],
    output: str,
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *_: object())
    monkeypatch.setattr(
        transfers,
        "status",
        lambda *_: {"push": push, "pull": pull, "conflicts": conflicts},
    )
    cli.main(["status"])
    assert capsys.readouterr().out == output + "\n"


@pytest.mark.parametrize("direction", ["push", "pull", "sync"])
def test_transfer_compile_is_opt_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *_: object())
    calls = []

    def transfer(*args: Any, **kwargs: Any) -> str:
        calls.append(kwargs["compile"])
        return ""

    monkeypatch.setattr(transfers, "execute_transfer", transfer)
    cli.main([direction])
    cli.main([direction, "--compile"])
    assert calls == [False, True]


def test_sync_push_alias_is_rejected() -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["sync", "--push"])
    assert error.value.code == 2

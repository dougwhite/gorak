from pathlib import Path
from typing import Any

import pytest

from gorak import cli, transfers
from gorak.connection import OpenRoadConnection


@pytest.mark.parametrize(
    ("command", "direction"),
    [
        (["pull"], "pull"),
        (["sync"], "pull"),
        (["push"], "push"),
        (["sync", "--push"], "push"),
    ],
)
def test_transfer_aliases(
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

    monkeypatch.setattr(transfers, direction, run)
    cli.main(command)
    assert calls == [direction]


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
    monkeypatch.setattr(
        transfers,
        "push",
        lambda *a, **k: transfers.Result(
            "push", ["example/good"], {"example/bad": "rejected"}
        ),
    )
    with pytest.raises(SystemExit) as error:
        cli.main(["push", "--no-compile"])
    assert error.value.code == 1
    assert "1 succeeded, 1 failed" in capsys.readouterr().err

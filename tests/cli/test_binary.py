import pytest

from gorak import cli
from gorak.errors import ProjectError


def test_version_does_not_load_project(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*args: object) -> None:
        raise AssertionError("version must not load project settings")

    monkeypatch.setattr(cli, "load_context", fail)
    with pytest.raises(SystemExit) as exit:
        cli.main(["--version"])
    assert exit.value.code == 0
    assert capsys.readouterr().out.startswith("gorak ")


def test_python_installation_rejects_self_update(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit:
        cli.main(["--self-update"])
    assert exit.value.code == 1
    assert "package manager" in capsys.readouterr().err


def test_self_update_dispatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak import binary_install

    monkeypatch.setattr(binary_install, "self_update", lambda: "Updated gorak")
    cli.main(["--self-update"])
    assert capsys.readouterr().out == "Updated gorak\n"

    def fail() -> str:
        raise ProjectError("offline")

    monkeypatch.setattr(binary_install, "self_update", fail)
    with pytest.raises(SystemExit) as exit:
        cli.main(["--self-update"])
    assert exit.value.code == 1
    assert "offline" in capsys.readouterr().err


def test_update_cannot_be_combined_with_a_source_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit:
        cli.main(["--self-update", "new", "example"])
    assert exit.value.code == 1
    assert "without a subcommand" in capsys.readouterr().err

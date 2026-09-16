from pathlib import Path
from typing import Any

import pytest

from gorak import cli, compiler, local, remote
from gorak.connection import OpenRoadConnection
from gorak.remote import RemoteHost


@pytest.mark.parametrize("failed", [False, True])
def test_local_compile_keeps_full_log_and_component_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    log = tmp_path / "compile.log"
    commands = []
    diagnostics = "\n".join(f"Compiler detail {i}" for i in range(30))

    def run(command: list[str]) -> str:
        commands.append(command)
        log.write_text(diagnostics + ("\nERROR: failed compilation" if failed else ""))
        if failed:
            raise local.LocalCommandError("process returned 1")
        return ""

    monkeypatch.setattr(local, "run_subprocess", run)
    result = compiler.compile_source(
        OpenRoadConnection("local", "node", "db", None), "example", "widget", log
    )
    assert result.success is not failed
    assert diagnostics in result.diagnostics()
    assert commands[0][1] == "compileapp"
    assert all(flag in commands[0] for flag in ("-cwidget", "-f", "-e"))


@pytest.mark.parametrize(
    "output",
    [
        "GORAK_COMPILE_OK\n",
        "ERROR: bad source\nGORAK_COMPILE_OK\n",
        "no completion marker",
    ],
)
def test_remote_compile_requires_completion_and_retains_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str
) -> None:
    calls = []
    monkeypatch.setattr(remote, "verify_remote_helpers", lambda h: None)

    def run(command: list[str]) -> str:
        calls.append(command)
        return output

    monkeypatch.setattr(remote, "run_subprocess", run)
    connection = OpenRoadConnection(
        "remote",
        "node",
        "db",
        RemoteHost("user", "host", r"C:\Tools With Spaces\gorak"),
    )
    result = compiler.compile_source(
        connection, "example", None, tmp_path / "compile.log"
    )
    assert result.success == (output == "GORAK_COMPILE_OK\n")
    assert result.diagnostics() == output
    assert 'compile-source.bat" "node::db" "example" "-"' in calls[0][-1]


def test_compile_cli_reports_all_diagnostics_and_failure_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "resolve_openroad_connection",
        lambda *a: OpenRoadConnection("local", "node", "db", None),
    )
    diagnostics = "\n".join(f"Error detail {i}" for i in range(30))

    def compile_source(
        c: Any, a: str, n: str | None, log: Path
    ) -> compiler.CompileResult:
        assert (a, n) == ("example", "widget")
        log.parent.mkdir(parents=True)
        log.write_text(diagnostics)
        return compiler.CompileResult(False, log)

    monkeypatch.setattr(compiler, "compile_source", compile_source)
    with pytest.raises(SystemExit) as ex:
        cli.main(["compile", "example", "widget"])
    assert ex.value.code == 1
    assert diagnostics in capsys.readouterr().err

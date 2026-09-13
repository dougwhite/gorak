from pathlib import Path

import pytest
from pytest import MonkeyPatch

from gorak import import_backend, local, remote
from gorak.connection import OpenRoadConnection
from gorak.project import ProjectError
from gorak.remote import RemoteCommandError, RemoteHost


def test_local_import_scopes_component_and_detects_compile_error(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    log = tmp_path / "import.log"
    calls: list[list[str]] = []

    def run(command: list[str]) -> str:
        calls.append(command)
        log.write_text("ERROR: compilation failed")
        return ""

    monkeypatch.setattr(local, "run_subprocess", run)
    with pytest.raises(ProjectError, match="compilation error"):
        import_backend.import_component_xml(
            OpenRoadConnection("local", "node", "demo", None),
            "app",
            "example",
            tmp_path / "source.xml",
            log,
        )
    assert calls[0][1:5] == ["backupapp", "in", "node::demo", "app"]
    assert "-cexample" in calls[0]
    assert "-f" in calls[0]
    assert "-nreplace" in calls[0]
    assert "compilation failed" in log.read_text()


@pytest.mark.parametrize("failure", [False, True])
def test_remote_import_quotes_paths_and_retains_diagnostics(
    tmp_path: Path, monkeypatch: MonkeyPatch, failure: bool
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str]) -> str:
        calls.append(command)
        if command[0] == "ssh":
            if failure:
                raise RemoteCommandError("compiler failed")
            return "Compiling example . . . done.\nGORAK_IMPORT_OK\n"
        return ""

    monkeypatch.setattr(remote, "run_subprocess", run)
    connection = OpenRoadConnection(
        "remote",
        "node",
        "demo",
        RemoteHost("developer", "windows-host", r"C:\Development Tools\gorak"),
    )
    log = tmp_path / "import.log"
    if failure:
        with pytest.raises(RemoteCommandError):
            import_backend.import_component_xml(
                connection, "app", "example", tmp_path / "source.xml", log
            )
        assert "compiler failed" in log.read_text()
    else:
        import_backend.import_component_xml(
            connection, "app", "example", tmp_path / "source.xml", log
        )
        assert "GORAK_IMPORT_OK" in log.read_text()
    assert calls[0][0] == "scp"
    assert calls[1][-1].startswith(
        '"C:\\Development Tools\\gorak\\import-component.bat" "node::demo" "app" "example" '
    )


@pytest.mark.parametrize(
    "root", [r"C:\bad%ROOT%", r"C:\bad!root", r"C:\bad&root", 'C:\\bad"root']
)
def test_rejects_remote_shell_metacharacters(
    tmp_path: Path, monkeypatch: MonkeyPatch, root: str
) -> None:
    monkeypatch.setattr(
        remote,
        "run_subprocess",
        lambda *a: pytest.fail("must not execute"),
    )
    with pytest.raises(ProjectError, match="metacharacters"):
        import_backend.import_component_xml(
            OpenRoadConnection(
                "remote", "node", "demo", RemoteHost("developer", "host", root)
            ),
            "app",
            "example",
            tmp_path / "source.xml",
            tmp_path / "log",
        )

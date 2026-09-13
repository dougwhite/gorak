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


def test_empty_application_creation_aborts_on_collision_without_compile(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = tmp_path / "source.xml"
    source.write_text('<OPENROAD><APPLICATION name="example"/></OPENROAD>')
    log = tmp_path / "import.log"
    calls: list[list[str]] = []

    def run(command: list[str]) -> str:
        calls.append(command)
        log.write_text("Application imported")
        return ""

    monkeypatch.setattr(local, "run_subprocess", run)
    import_backend.import_component_xml(
        OpenRoadConnection("local", "node", "demo", None),
        "example",
        "-",
        source,
        log,
        create=True,
    )
    assert "-nabort" in calls[0]
    assert "-nreplace" not in calls[0]
    assert "-f" not in calls[0]
    assert not any(arg.startswith("-c") for arg in calls[0])


def test_remote_creation_uses_separate_helper(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str]) -> str:
        calls.append(command)
        return "GORAK_IMPORT_OK\n"

    monkeypatch.setattr(remote, "run_subprocess", run)
    import_backend.import_component_xml(
        OpenRoadConnection(
            "remote", "node", "demo", RemoteHost("user", "host", r"C:\gorak")
        ),
        "example",
        "procedure",
        tmp_path / "source.xml",
        tmp_path / "log",
        create=True,
    )
    assert "create-source.bat" in calls[1][-1]
    assert calls[1][-1].endswith('"create"')


def test_application_update_compiles_in_fresh_process(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = tmp_path / "source.xml"
    source.write_text(
        '<OPENROAD><APPLICATION name="example"/><COMPONENT name="proc"/></OPENROAD>'
    )
    log = tmp_path / "import.log"
    calls: list[list[str]] = []

    def run(command: list[str]) -> str:
        calls.append(command)
        target = next(arg[2:] for arg in command if arg.startswith("-L"))
        Path(target).write_text("Complete")
        return ""

    monkeypatch.setattr(local, "run_subprocess", run)
    import_backend.import_component_xml(
        OpenRoadConnection("local", "node", "demo", None),
        "example",
        "-",
        source,
        log,
    )
    assert calls[0][1] == "backupapp"
    assert "-f" not in calls[0]
    assert calls[1][1] == "compileapp"


def test_component_named_error_is_not_a_compiler_error() -> None:
    import_backend.checked_log(
        "Loading Error into database . . . done.\nCompiling error . . . done."
    )
    with pytest.raises(ProjectError):
        import_backend.checked_log("ERROR: Compile errors in component example.")

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gorak.project import ProjectError
from gorak.writer_artifact import writer_environment
from gorak.writer_settings import installation_startup_value

VARIABLE = "ING_SET_SOURCE"


@pytest.fixture
def installation(tmp_path: Path) -> tuple[dict[str, str], Path]:
    executable = (
        tmp_path
        / "ingres"
        / "utility"
        / ("ingprenv.exe" if os.name == "nt" else "ingprenv")
    )
    executable.parent.mkdir(parents=True)
    executable.touch()
    return {"II_SYSTEM": str(tmp_path), "PRESERVE": "value"}, executable


def test_queries_only_named_symbol_using_selected_installation(
    installation: tuple[dict[str, str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    env, executable = installation

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert command == [str(executable), VARIABLE]
        assert kwargs["env"] == env
        assert kwargs["timeout"] == 10
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(
            command, 0, b"  set date_format 'multinational'; -- caf\xe9\r\n", b""
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert (
        installation_startup_value(VARIABLE, env, encoding="cp1252")
        == "  set date_format 'multinational'; -- café"
    )


@pytest.mark.parametrize(
    "output,code,error",
    [
        (b"", 1, b""),
        (b"secret", 0, b"warning"),
        (b"x" * (1024 * 1024 + 1), 0, b""),
        (b"\xff", 0, b""),
        (b"\0", 0, b""),
    ],
)
def test_bad_lookup_is_not_an_empty_setting(
    installation: tuple[dict[str, str], Path],
    monkeypatch: pytest.MonkeyPatch,
    output: bytes,
    code: int,
    error: bytes,
) -> None:
    env, _ = installation
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], code, output, error),
    )
    with pytest.raises(ProjectError) as caught:
        installation_startup_value(VARIABLE, env, encoding="utf-8")
    assert "secret" not in str(caught.value) and "warning" not in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [OSError("secret"), subprocess.TimeoutExpired("ingprenv", 10, output=b"secret")],
)
def test_subprocess_failure_does_not_leak_startup(
    installation: tuple[dict[str, str], Path],
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    env, _ = installation

    def run(*args: Any, **kwargs: Any) -> None:
        raise failure

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ProjectError) as caught:
        installation_startup_value(VARIABLE, env, encoding="ascii")
    assert "secret" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_absent_symbol_is_empty_and_default_artifact_lookup_is_used(
    installation: tuple[dict[str, str], Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env, _ = installation
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0, b"", b"")
    )
    assert installation_startup_value(VARIABLE, env, encoding="ascii") == ""
    with writer_environment(
        env, "source", encoding="ascii", temporary_root=tmp_path
    ) as child:
        path = Path(child[VARIABLE][8:])
        assert path.read_text().startswith('set lockmode on "$ingres".')
    assert not path.exists()


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"II_SYSTEM": "relative"},
        {"II_SYSTEM": ""},
        {"II_SYSTEM": "/first", "ii_system": "/second"},
    ],
)
def test_missing_or_ambiguous_installation_is_not_path_lookup(
    env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("gorak.writer_settings._WINDOWS_ENV", True)
    with pytest.raises(ProjectError):
        installation_startup_value(VARIABLE, env, encoding="ascii")


def test_invalid_variable_and_missing_executable(tmp_path: Path) -> None:
    with pytest.raises(ProjectError):
        installation_startup_value("", {"II_SYSTEM": str(tmp_path)}, encoding="ascii")
    with pytest.raises(ProjectError, match="Cannot find ingprenv"):
        installation_startup_value(
            VARIABLE, {"II_SYSTEM": str(tmp_path)}, encoding="ascii"
        )


@pytest.mark.parametrize(
    "windows,expected",
    [(True, ["ING_SET_SOURCE", "ing_set_source"]), (False, ["ING_SET_SOURCE"])],
)
def test_environment_names_follow_execution_host(
    windows: bool, expected: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.writer_settings import environment_keys

    monkeypatch.setattr("gorak.writer_settings._WINDOWS_ENV", windows)
    assert (
        environment_keys({"ING_SET_SOURCE": "one", "ing_set_source": "two"}, VARIABLE)
        == expected
    )


def test_lookup_failure_prevents_artifact_creation(
    installation: tuple[dict[str, str], Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env, _ = installation
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1, b"", b"")
    )
    with pytest.raises(ProjectError):
        with writer_environment(
            env, "source", encoding="ascii", temporary_root=tmp_path
        ):
            pytest.fail("launch should be blocked")
    assert not list(tmp_path.glob("gorak-init-*"))


def test_posix_installation_name_is_case_sensitive(
    installation: tuple[dict[str, str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    env, _ = installation
    env["ii_system"] = "ignored lowercase value"
    monkeypatch.setattr("gorak.writer_settings._WINDOWS_ENV", False)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0, b"", b"")
    )
    assert installation_startup_value(VARIABLE, env, encoding="ascii") == ""

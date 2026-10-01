"""Keep automated tests independent of developer connection settings and services."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def isolate_external_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(("GORAK_", "OR_UNITTEST_")):
            monkeypatch.delenv(key)

    def deny_database(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Tests must mock database connections")

    # Native ODBC is optional; keep the connection guard when it is available.
    try:
        import pyodbc
    except ImportError:
        pass
    else:
        monkeypatch.setattr(pyodbc, "connect", deny_database)
    original_popen = subprocess.Popen

    def isolated_popen(command: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(command, (str, bytes)) or kwargs.get("shell"):
            raise AssertionError("Tests must mock shell commands")
        executable = shutil.which(str(command[0]))
        # Permit this interpreter only for an explicit temporary script/archive.
        # Never allow arbitrary -c/-m commands or the installed OpenROAD tools.
        temporary_script = (
            executable is not None
            and Path(executable).resolve() == Path(sys.executable).resolve()
            and len(command) > 1
            and Path(str(command[1])).is_absolute()
            and Path(str(command[1])).resolve().is_relative_to(tmp_path)
            and Path(str(command[1])).suffix in {".py", ".pyz"}
            and Path(str(command[1])).is_file()
        )
        if not temporary_script and (
            executable is None
            or not Path(executable).resolve().is_relative_to(tmp_path)
        ):
            raise AssertionError(
                "Tests must mock external commands or use a temporary fake executable"
            )
        return original_popen(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", isolated_popen)

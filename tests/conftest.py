"""Keep automated tests independent of developer connection settings and services."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pyodbc
import pytest


@pytest.fixture(autouse=True)
def isolate_external_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith(("GORAK_", "OR_UNITTEST_")):
            monkeypatch.delenv(key)

    def deny_database(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Tests must mock database connections")

    monkeypatch.setattr(pyodbc, "connect", deny_database)
    original_popen = subprocess.Popen

    def isolated_popen(command: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(command, (str, bytes)) or kwargs.get("shell"):
            raise AssertionError("Tests must mock shell commands")
        executable = shutil.which(str(command[0]))
        if executable is None or not Path(executable).resolve().is_relative_to(
            tmp_path
        ):
            raise AssertionError(
                "Tests must mock external commands or use a temporary fake executable"
            )
        return original_popen(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", isolated_popen)

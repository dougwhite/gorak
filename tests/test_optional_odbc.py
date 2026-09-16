"""Fresh-process coverage of startup with an unavailable native ODBC runtime."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# This test launches only Python with fixed test code, never a service command.
_POPEN = subprocess.Popen


@pytest.mark.parametrize(
    "failure",
    [
        "ImportError('libodbc.so.2: cannot open shared object file')",
        "ModuleNotFoundError(\"No module named 'pyodbc'\")",
    ],
)
def test_cli_without_odbc_runtime(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = """
import importlib.abc
import sys
from pathlib import Path
from unittest.mock import patch

attempts = []
class MissingOdbc(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pyodbc":
            attempts.append(fullname)
            raise FAILURE

sys.meta_path.insert(0, MissingOdbc())
from gorak import cli
from gorak import export

try:
    cli.main(["--help"])
except SystemExit as error:
    assert error.code == 0
cli.main(["new", "--nogit", "sample"])
assert Path("sample/gorak.json").exists()

common = ["--vnode", "example", "--database", "sample"]
with patch.object(export, "local_get_app_list", return_value=[]) as local:
    cli.main(["app", "list", "--backend", "local", *common])
    local.assert_called_once()
with patch.object(export, "get_app_list", return_value=[]) as remote:
    cli.main(["app", "list", "--backend", "remote", "--user", "test",
              "--host", "example", "--gorak-root", "C:/gorak", *common])
    remote.assert_called_once()
assert attempts == [], attempts

try:
    cli.main(["app", "list", "--sql-backend", "odbc", *common,
              "--db-driver", "Ingres AC", "--db-host", "example",
              "--db-listen-address", "II7", "--db-user", "test",
              "--db-password", "test"])
except SystemExit as error:
    assert error.code == 1
else:
    raise AssertionError("ODBC must fail without its runtime")
assert attempts == ["pyodbc"], attempts
""".replace("FAILURE", failure)
    monkeypatch.setattr(subprocess, "Popen", _POPEN)
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ERROR: ODBC backend error" in result.stderr
    assert "libodbc.so.2" in result.stderr
    assert "apt install libodbc2" in result.stderr
    assert "GORAK_DB_DRIVER" in result.stderr
    assert "Traceback" not in result.stderr


def test_engine_loads_driver_and_preserves_connection_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import ModuleType
    from unittest.mock import Mock

    from gorak import database

    driver = ModuleType("pyodbc")
    connect = Mock(return_value=object())
    monkeypatch.setattr(driver, "connect", connect, raising=False)
    monkeypatch.setitem(sys.modules, "pyodbc", driver)
    engine_factory = Mock()
    monkeypatch.setattr(database, "create_engine", engine_factory)
    settings = database.OdbcSettings(
        "Ingres AC", "example", "II7", "sample", "test", "test"
    )

    assert database.create_odbc_engine(settings) is engine_factory.return_value
    connect.assert_not_called()
    assert engine_factory.call_args.args == ("ingres://",)
    creator = engine_factory.call_args.kwargs["creator"]
    assert creator() is connect.return_value
    connect.assert_called_once_with(database.build_odbc_connection_string(settings))

"""Load the native ODBC driver only when an ODBC engine is requested."""

import importlib
import sys
from types import ModuleType
from typing import cast

from sqlalchemy.exc import SQLAlchemyError


class OdbcRuntimeError(RuntimeError):
    """The optional ODBC driver or its native runtime cannot be loaded."""


def load_pyodbc() -> ModuleType:
    try:
        return importlib.import_module("pyodbc")
    except ImportError as error:
        raise OdbcRuntimeError(
            "ODBC support could not load pyodbc or its native runtime. "
            "On Linux, install the unixODBC runtime providing libodbc.so.2 "
            "(Debian/Ubuntu: apt install libodbc2; Fedora: dnf install unixODBC). "
            "Install/configure the Actian Ingres ODBC driver and GORAK_DB_DRIVER; "
            "if pyodbc is missing, reinstall Gorak's Python dependencies. "
            "See docs/config.md. Local/SSH workflows do not require ODBC."
        ) from error


def odbc_error_types(
    *additional: type[Exception],
) -> tuple[type[Exception], ...]:
    """Recognize native errors without importing a driver merely to catch them."""

    errors: tuple[type[Exception], ...] = (SQLAlchemyError, OdbcRuntimeError)
    module = sys.modules.get("pyodbc")
    if module is not None:
        errors += (cast(type[Exception], module.Error),)
    return errors + additional

"""Scoped execution-host startup files for revision-aware OpenROAD launchers."""

import codecs
import os
import re
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .project import ProjectError
from .revision_installation import REVISION_TABLE
from .writer_init import compose_writer_init
from .writer_settings import environment_keys, installation_startup_value

MAX_STARTUP_BYTES = 1024 * 1024


def startup_variable(database: str) -> str:
    """Scope counter settings to the source database, not runtime connections."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", database):
        raise ProjectError("Writer startup requires a simple source database name")
    return f"ING_SET_{database.upper()}"


@contextmanager
def writer_environment(
    environment: Mapping[str, str],
    database: str,
    *,
    installation_value: Callable[[str], str] | None = None,
    encoding: str,
    temporary_root: Path | None = None,
) -> Iterator[dict[str, str]]:
    """Create an execution-host include and yield a private child environment.

    Run this on the OpenROAD execution host and choose its source encoding.
    Default symbol lookup uses the child's II_SYSTEM installation; an injected
    resolver must observe the same execution-host and installation boundary.
    No connection or installation verification is implied. The child must finish
    before leaving this context (including timeout termination).
    """
    variable = startup_variable(database)
    child = dict(environment)
    # Windows environment names are case-insensitive. Reject ambiguous mappings
    # rather than quietly picking one value on another host.
    keys = environment_keys(child, variable)
    if len(keys) > 1:
        raise ProjectError("Ambiguous database startup environment")
    # Ingres treats an empty process value as unset and reads the symbol table.
    if keys and child[keys[0]]:
        existing = child[keys[0]]
    elif installation_value is not None:
        existing = installation_value(variable)
    else:
        existing = installation_startup_value(variable, child, encoding=encoding)
    if not isinstance(existing, str):
        raise ProjectError("Invalid installation startup value")
    try:
        codec = codecs.lookup(encoding)
        # Wide/BOM-prefixed output is not an Ingres startup text file.
        if "set".encode(codec.name) != b"set":
            raise ValueError
    except (LookupError, ValueError) as ex:
        raise ProjectError("Unsupported writer startup encoding") from ex

    def read_include(value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            raise ProjectError("Startup include is not an execution-host absolute path")
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_STARTUP_BYTES + 1)
            if len(data) > MAX_STARTUP_BYTES:
                raise ProjectError("Writer startup include exceeds size limit")
            return data.decode(codec.name, errors="strict")
        except (OSError, UnicodeError) as ex:
            raise ProjectError("Cannot read writer startup include") from ex

    try:
        if len(existing.encode(codec.name, errors="strict")) > MAX_STARTUP_BYTES:
            raise ProjectError("Writer startup value exceeds size limit")
        sql = compose_writer_init(existing, REVISION_TABLE, read_include=read_include)
        payload = sql.encode(codec.name, errors="strict")
    except UnicodeError as ex:
        raise ProjectError(
            "Writer startup is not representable in configured encoding"
        ) from ex
    if len(payload) > MAX_STARTUP_BYTES:
        raise ProjectError("Composed writer startup exceeds size limit")
    with tempfile.TemporaryDirectory(
        prefix="gorak-init-", dir=temporary_root
    ) as directory:
        path = Path(directory).resolve() / "startup.sql"
        include = f"include {path}"
        # Only the child environment carries this path; no shell interpolation.
        if (
            any(c in str(path) for c in '\r\n\0"')
            or len(include.encode(codec.name)) > 256
        ):
            raise ProjectError("Writer startup include path exceeds Ingres limits")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        for key in keys:
            del child[key]
        child[variable] = include
        yield child

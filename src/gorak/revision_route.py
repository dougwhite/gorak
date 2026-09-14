"""Verify the source execution route against the configured ODBC generation."""

import os
import re
import subprocess
from importlib.resources import files
from pathlib import Path

from .connection import OpenRoadConnection, require_remote_host
from .errors import ProjectError
from .remote import build_remote_command, verify_remote_helpers
from .sql_output import table_rows
from .writer_settings import environment_keys


def validate_source_route(connection: OpenRoadConnection) -> None:
    """Read identity through the same installation/vnode used for OpenROAD.

    Physical clones must receive a fresh generation before use. Vnode changes and
    database maintenance must be offline: this read is not a route configuration lock.
    """
    if not connection.revision_generation:
        return
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", connection.vnode) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]{0,31}", connection.database
    ):
        raise ProjectError("Managed source route requires simple vnode/database names")
    query = None
    if connection.backend == "remote":
        from .remote import session_command

        remote = require_remote_host(connection)
        verify_remote_helpers(remote)
        command = session_command(
            build_remote_command(
                remote,
                "get-revision-generation.bat",
                [connection.vnode, connection.database],
            )
        )
    else:
        systems = [os.environ[key] for key in environment_keys(os.environ, "II_SYSTEM")]
        if len(systems) != 1 or not Path(systems[0]).is_absolute():
            raise ProjectError(
                "Source route verification requires an absolute II_SYSTEM"
            )
        executable = (
            Path(systems[0]) / "ingres/bin" / ("sql.exe" if os.name == "nt" else "sql")
        )
        command = [str(executable), f"{connection.vnode}::{connection.database}"]
        query = (
            files("gorak.remote_scripts")
            .joinpath("revision-generation.sql")
            .read_text()
        )
    try:
        result = subprocess.run(
            command,
            input=query,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ProjectError("Cannot verify OpenROAD source route generation") from None
    rows = table_rows(result.stdout, 1, "revision_id")
    if (
        result.returncode
        or re.search(r"\bE_[A-Z0-9_]+", result.stdout + result.stderr)
        or rows != [[connection.revision_generation]]
    ):
        raise ProjectError(
            "OpenROAD source route does not match the configured generation"
        )

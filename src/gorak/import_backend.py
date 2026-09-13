"""Backend transport for component-scoped, compiled XML imports."""

import re
from pathlib import Path
from uuid import uuid4

from . import local, remote
from .connection import OpenRoadConnection, require_remote_host
from .project import ProjectError


def checked_log(text: str) -> None:
    if re.search(r"\b(error|failed|failure)\b|\bE_[A-Z0-9_]+", text, re.IGNORECASE):
        raise ProjectError(
            "OpenROAD reported an import/compilation error; inspect import.log"
        )


def import_component_xml(
    connection: OpenRoadConnection,
    app: str,
    component: str,
    xml_path: Path,
    log_path: Path,
) -> None:
    """Import only the named component; keep diagnostics even when execution fails."""
    if connection.backend == "local":
        command = local.build_backup_component_command(
            connection.vnode,
            connection.database,
            app,
            component,
            xml_path,
            log_path,
        )
        command[2] = "in"
        command.extend(["-nreplace", "-f"])
        try:
            output = local.run_subprocess(command)
        except Exception as ex:
            with log_path.open("a") as log:
                log.write(f"\n{ex}\n")
            raise
        if not log_path.is_file():
            log_path.write_text(output)
            raise ProjectError(
                "OpenROAD did not create a compilation log; inspect import.log"
            )
        checked_log(log_path.read_text(errors="replace"))
        return

    host = require_remote_host(connection)
    # cmd.exe expands percent/exclamation characters even inside double quotes.
    # Restrict this initial write path rather than applying incomplete escaping.
    values = [connection.vnode, connection.database, app, component]
    if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in values):
        raise ProjectError(
            "Remote import connection and component names contain unsupported characters"
        )
    if not re.fullmatch(r"[A-Za-z]:\\[A-Za-z0-9_ .\\-]+", host.gorak_root):
        raise ProjectError(
            "Remote import requires a Windows root without shell metacharacters"
        )
    token = uuid4().hex
    destination = f"{host.gorak_root}\\import-{token}.xml"
    remote.run_subprocess(remote.build_upload_command(host, str(xml_path), destination))
    args = [f"{connection.vnode}::{connection.database}", app, component, destination]
    command = [
        "ssh",
        "-T",
        host.ssh_target,
        " ".join(
            f'"{value}"'
            for value in [f"{host.gorak_root}\\import-component.bat", *args]
        ),
    ]
    try:
        output = remote.run_subprocess(command)
    except Exception as ex:
        log_path.write_text(str(ex))
        raise
    log_path.write_text(output)
    checked_log(output)
    if "GORAK_IMPORT_OK" not in output.splitlines():
        raise ProjectError(
            "Remote helper did not confirm import; reinstall helpers and inspect import.log"
        )

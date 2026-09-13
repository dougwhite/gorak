"""Apply the DBA script using the explicitly configured execution backend."""

import base64
import os
import re
import subprocess
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from .connection import OpenRoadConnection, require_odbc_settings, require_remote_host
from .installation import installation_sql
from .installation_check import InstallationCheck, check_installation
from .project import ProjectError
from .remote import build_upload_command, run_subprocess, session_command


def install_command(
    connection: OpenRoadConnection, remote_sql: str | None = None
) -> list[str]:
    target = f"{connection.vnode}::{connection.database}"
    if connection.backend == "local":
        return ["sql", "-u$ingres", target]
    remote = require_remote_host(connection)
    # Encoded PowerShell avoids cmd.exe expansion of vnode/database input.
    if remote_sql is None:
        raise ProjectError("Remote installation requires a staged SQL file")
    sql_literal = remote_sql.replace("'", "''")
    literal = target.replace("'", "''")
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "if (-not $env:II_SYSTEM) { $env:II_SYSTEM = 'C:\\Program Files\\Ingres\\ingresWD' }; "
        '$env:PATH = "$env:II_SYSTEM\\ingres\\bin;$env:II_SYSTEM\\ingres\\utility;$env:PATH"; '
        "$env:II_TM_EXIT_ON_ERROR = 'rollback'; "
        f"$sql = Get-Content -Raw -LiteralPath '{sql_literal}'; "
        f"$sql | & \"$env:II_SYSTEM\\ingres\\bin\\sql.exe\" '-u$ingres' '{literal}'; "
        f"$code = $LASTEXITCODE; Remove-Item -LiteralPath '{sql_literal}'; exit $code"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return session_command(
        [
            "ssh",
            "-T",
            remote.ssh_target,
            f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}",
        ]
    )


def install_tracking(
    connection: OpenRoadConnection, artifact_root: Path, *, upgrade: bool = False
) -> InstallationCheck:
    settings = require_odbc_settings(connection)
    if settings.database != connection.database:
        raise ProjectError("Installation SQL and ODBC database targets differ")
    # Validate access before mutation. Existing/partial installations require DBA review.
    before = check_installation(settings)
    if before.status == "capture_only_inventory_present":
        if before.schema_version == 2:
            return before
        if not upgrade:
            raise ProjectError(
                "Tracking schema v1 is installed; run gorak install --upgrade"
            )
    elif upgrade:
        raise ProjectError("Upgrade requires a complete version 1 installation")
    elif before.tracking_objects_present:
        raise ProjectError(
            "Existing or partial tracking installation; ask the DBA to review it"
        )
    artifacts = artifact_root / uuid4().hex
    artifacts.mkdir(parents=True)
    reader = settings.user.replace('"', '""')
    if not reader or any(c in reader for c in "\r\n\x00"):
        raise ProjectError("Invalid ODBC reader identity")
    grants = (
        f'grant select on gorak_tracking_install to "{reader}";\n\\g\n'
        f'grant select on gorak_change_events to "{reader}";\n\\g\n'
        f'grant select, insert on gorak_journal_acks to "{reader}";\n\\g\n'
    )
    script = (
        installation_sql(upgrade=upgrade)
        .replace(
            "-- No grants are issued. DBA controls read access; developers need no owner login.",
            "-- Direct install grants tracking SELECT and acknowledgment INSERT to the ODBC user.",
        )
        .replace("commit;\n\\g\n", grants + "commit;\n\\g\n")
    )
    (artifacts / "install.sql").write_text(script, encoding="utf-8")
    remote_sql = None
    if connection.backend == "remote":
        remote = require_remote_host(connection)
        remote_sql = str(
            PureWindowsPath(remote.gorak_root) / f"gorak-install-{artifacts.name}.sql"
        )
        run_subprocess(
            build_upload_command(remote, str(artifacts / "install.sql"), remote_sql)
        )
    env = dict(os.environ, II_TM_EXIT_ON_ERROR="rollback")
    try:
        result = subprocess.run(
            install_command(connection, remote_sql),
            input=script if connection.backend == "local" else None,
            text=True,
            capture_output=True,
            env=env,
            timeout=120,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as ex:
        raise ProjectError(
            f"Installation execution interrupted; inspect the target before retrying. Artifacts: {artifacts}"
        ) from ex
    output = result.stdout + "\n" + result.stderr
    (artifacts / "install.log").write_text(output, encoding="utf-8")
    if result.returncode or re.search(r"\bE_[A-Z0-9]+", output):
        raise ProjectError(
            f"Installation SQL failed; inspect {artifacts / 'install.log'}"
        )
    try:
        after = check_installation(settings)
    except Exception as ex:
        raise ProjectError(
            f"SQL finished but ODBC verification failed; installation may exist. Ask the DBA to check read grants. Artifacts: {artifacts}"
        ) from ex
    if (
        after.issues
        or after.schema_version != 2
        or (upgrade and after.installation_id != before.installation_id)
    ):
        raise ProjectError(
            f"Installation verification incomplete. Artifacts: {artifacts}"
        )
    return after

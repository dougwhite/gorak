"""Execute OpenROAD locally or through the Windows SSH runner helper."""

import json
import os
import re
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .connection import OpenRoadConnection, require_remote_host
from .project import ProjectError
from .remote import build_upload_command
from .runner import TestApplication
from .writer_launch import local_writer_command


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    timed_out: bool
    trace: str
    report: str
    trace_path: str
    output: str = ""


def command_args(database: str, suite: TestApplication, trace: str) -> list[str]:
    args = [
        "rundbapp",
        database,
        suite.application,
        "-nowindows",
        "-TALL,logonly",
        f"-L{trace}",
    ]
    if suite.component:
        args.append(f"-c{suite.component}")
    return args


def execute_application(
    connection: OpenRoadConnection,
    suite: TestApplication,
    env: dict[str, str],
    artifacts: Path,
    testing: bool,
) -> RunResult:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", suite.application):
        raise ProjectError("Invalid application name")
    if suite.component and not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]{0,31}", suite.component
    ):
        raise ProjectError("Invalid starting component name")
    if not 1 <= suite.timeout_seconds <= 86400:
        raise ProjectError("Timeout must be between 1 and 86400 seconds")
    from .revision_check import validate_revision_target

    mode = env.get("GORAK_TRACE_MODE", "persistent")
    if mode not in {"persistent", "temp"}:
        raise ProjectError("GORAK_TRACE_MODE must be persistent or temp")
    runtime_env = {
        key.removeprefix("GORAK_RUN_ENV_"): value
        for key, value in env.items()
        if key.startswith("GORAK_RUN_ENV_")
    }
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in runtime_env):
        raise ProjectError("Invalid runtime environment variable name")
    if connection.revision_generation and any(
        key.upper() in {"II_SYSTEM", "II_CONFIG", "II_INSTALLATION"}
        or key.upper().startswith("II_GCN")
        for key in runtime_env
    ):
        raise ProjectError(
            "Managed runs cannot override Ingres installation or routing settings"
        )
    validate_revision_target(connection)
    artifacts.mkdir(parents=True, exist_ok=False)
    database = (
        f"{connection.vnode}::{connection.database}"
        if connection.vnode
        else connection.database
    )
    if connection.backend == "local":
        result = execute_local(
            database,
            suite,
            env,
            runtime_env,
            artifacts,
            testing,
            mode,
            writer_database=connection.database
            if connection.revision_generation
            else None,
            writer_encoding=connection.writer_encoding,
        )
    else:
        result = execute_remote(
            connection, database, suite, env, runtime_env, testing, mode
        )
    (artifacts / "trace.log").write_text(result.trace, encoding="utf-8")
    (artifacts / "process.log").write_text(result.output, encoding="utf-8")
    if result.report:
        (artifacts / "results.xml").write_text(result.report, encoding="utf-8")
    (artifacts / "run.json").write_text(
        json.dumps(
            {
                "application": suite.application,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "trace_path": result.trace_path,
            },
            indent=2,
        )
    )
    return result


def execute_local(
    database: str,
    suite: TestApplication,
    env: dict[str, str],
    runtime_env: dict[str, str],
    artifacts: Path,
    testing: bool,
    mode: str,
    *,
    writer_database: str | None = None,
    writer_encoding: str = "cp1252",
) -> RunResult:
    with tempfile.TemporaryDirectory(prefix="gorak-run-") as temporary:
        trace_root = (
            Path(temporary)
            if mode == "temp"
            else Path(env.get("GORAK_TRACE_DIR", str(artifacts)))
        )
        trace_root.mkdir(parents=True, exist_ok=True)
        token = uuid4().hex
        trace = trace_root / f"{suite.application}-{token}.log"
        report = trace_root / f"{suite.application}-{token}.xml"
        child_env = dict(os.environ)
        child_env.update(runtime_env)
        if testing:
            child_env.update(
                OR_UNITTEST_GEN_XML_STATS="true",
                OR_UNITTEST_STATSFILE_XML=str(report.resolve()),
                OR_UNITTEST_STATSFILE=str(trace_root / f"{token}.stats.log"),
            )
        command = ["w4gldev", *command_args(database, suite, str(trace.resolve()))]
        if writer_database:
            child_env["GORAK_WRITER_TEMP_ROOT"] = temporary
        command = local_writer_command(command, writer_database, writer_encoding)
        with subprocess.Popen(
            command,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=os.name != "nt",
        ) as process:
            timed_out = False
            try:
                output, _ = process.communicate(timeout=suite.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                output, _ = process.communicate()
            return RunResult(
                124 if timed_out else process.returncode,
                timed_out,
                trace.read_text(errors="replace") if trace.exists() else "",
                report.read_text(encoding="utf-8") if report.exists() else "",
                str(trace),
                output,
            )


def execute_remote(
    connection: OpenRoadConnection,
    database: str,
    suite: TestApplication,
    env: dict[str, str],
    runtime_env: dict[str, str],
    testing: bool,
    mode: str,
) -> RunResult:
    host = require_remote_host(connection)
    if connection.revision_generation:
        from .remote import verify_remote_helpers

        verify_remote_helpers(host)
    if not re.fullmatch(r"[A-Za-z]:\\[A-Za-z0-9_ .\\-]+", host.gorak_root):
        raise ProjectError(
            "Runner helper root must be a Windows path without shell metacharacters"
        )
    token = uuid4().hex
    remote_request = f"{host.gorak_root}\\run-{token}.json"
    request = {
        "database": database,
        "application": suite.application,
        "component": suite.component,
        "timeout": suite.timeout_seconds,
        "trace_dir": env.get("GORAK_TRACE_DIR", ""),
        "trace_mode": mode,
        "testing": testing,
        "environment": runtime_env,
        "writer_database": connection.database
        if connection.revision_generation
        else None,
        "writer_encoding": connection.writer_encoding,
    }
    with tempfile.TemporaryDirectory(prefix="gorak-request-") as tmp:
        path = Path(tmp) / "request.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        path.chmod(0o600)
        subprocess.run(
            build_upload_command(host, str(path), remote_request),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        helper = f"{host.gorak_root}\\run-application.ps1"
        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-T",
            host.ssh_target,
            f'powershell -NoProfile -File "{helper}" -Request "{remote_request}"',
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=suite.timeout_seconds + 45
        )
    if completed.returncode != 0:
        raise ProjectError(
            f"Remote runner transport failed (exit {completed.returncode}); inspect helper installation/connectivity"
        )
    try:
        data: dict[str, Any] = json.loads(completed.stdout)
        if type(data["exit_code"]) is not int or type(data["timed_out"]) is not bool:
            raise ValueError("Invalid runner status")
        for key in ["trace", "report", "trace_path", "output"]:
            if not isinstance(data.get(key), str):
                raise ValueError(f"Invalid runner {key}")
        return RunResult(**data)
    except (ValueError, KeyError, TypeError) as ex:
        raise ProjectError(
            "Invalid remote runner response; reinstall remote helpers"
        ) from ex

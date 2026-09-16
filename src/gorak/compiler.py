"""Explicit database compilation, independent of source synchronization."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from . import local, remote
from .connection import OpenRoadConnection, require_remote_host
from .errors import PostPushCompilationError
from .import_backend import checked_log
from .importer import validate_name
from .project import ProjectError
from .writer_launch import local_writer_command, remote_writer_prefix


@dataclass(frozen=True)
class CompileResult:
    success: bool
    log: Path

    def diagnostics(self) -> str:
        return self.log.read_text(errors="replace")


def compile_source(
    connection: OpenRoadConnection, app: str, component: str | None, log: Path
) -> CompileResult:
    """Compile current database source and retain diagnostics, including failures."""
    from .revision_check import validate_revision_target

    validate_name(app)
    if component is not None:
        validate_name(component)
    validate_revision_target(connection)
    log.parent.mkdir(parents=True, exist_ok=True)
    run: Callable[[list[str]], str]
    if connection.backend == "local":
        command = local_writer_command(
            [
                "w4gldev",
                "compileapp",
                local.build_database_target(connection.vnode, connection.database),
                app,
                "-nowindows",
                "-e",
                "-f",
                *([f"-c{component}"] if component else []),
                "-TALL,logonly",
                f"-L{local.command_path(log)}",
            ],
            connection.database if connection.revision_generation else None,
            connection.writer_encoding,
        )
        run = local.run_subprocess
    else:
        host = require_remote_host(connection)
        if any(
            not re.fullmatch(r"[A-Za-z0-9_.-]+", value)
            for value in (connection.vnode, connection.database)
        ):
            raise ProjectError(
                "Remote compile connection names contain unsupported characters"
            )
        if not re.fullmatch(r"[A-Za-z]:\\[A-Za-z0-9_ .\\-]+", host.gorak_root):
            raise ProjectError("Remote compile root contains shell metacharacters")
        remote.verify_remote_helpers(host)
        args = [
            f"{host.gorak_root}\\compile-source.bat",
            f"{connection.vnode}::{connection.database}",
            app,
            component or "-",
            f"{host.gorak_root}\\compile-{uuid4().hex}.log",
        ]
        command = [
            "ssh",
            "-T",
            host.ssh_target,
            remote_writer_prefix(host.writer_database, host.writer_encoding)
            + " ".join(f'"{value}"' for value in args),
        ]
        run = remote.run_subprocess
    try:
        output = run(command)
    except Exception as ex:
        with log.open("a") as handle:
            handle.write(f"\n{ex}\n")
        return CompileResult(False, log)
    if connection.backend != "local":
        log.write_text(output)
        if "GORAK_COMPILE_OK" not in output.splitlines():
            return CompileResult(False, log)
    elif not log.exists():
        log.write_text(output + "\nOpenROAD did not create a compilation log.\n")
        return CompileResult(False, log)
    try:
        checked_log(log.read_text(errors="replace"))
    except ProjectError:
        return CompileResult(False, log)
    return CompileResult(True, log)


def compile_command(
    connection: OpenRoadConnection, root: Path, app: str, component: str | None
) -> str:
    from .project_lock import project_lock
    from .sync_guard import binding_status, validate_tracking_health

    with project_lock(root, "compile", recover_push=True):
        binding_status(connection, root, recover_push=True)
        validate_tracking_health(connection, root)
        result = compile_source(
            connection,
            app,
            component,
            root / ".openroad/compiles" / uuid4().hex / "compile.log",
        )
        message = (
            f"Compiling database source: {app}"
            + (f"/{component}" if component else "")
            + f"\n{result.diagnostics()}\nFull log: {result.log}"
        )
        if not result.success:
            raise ProjectError(message)
        return message


def queue_compilation(root: Path, targets: list[tuple[str, str]]) -> None:
    """Keep compilation work across interrupted source pushes, separately from recovery."""
    from .push_retry import write_record

    path = root / ".openroad/compile-pending.json"
    existing: list[tuple[str, str]] = []
    if path.exists():
        try:
            existing = read_compile_queue(path)
        except (ValueError, TypeError, ProjectError):
            retained = path.with_name(f"compile-pending-invalid-{uuid4().hex}.json")
            retained.write_bytes(path.read_bytes())
    write_record(path, [list(t) for t in dict.fromkeys([*existing, *targets])])


def read_compile_queue(path: Path) -> list[tuple[str, str]]:
    import json

    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("Invalid compile queue")
    result = []
    for entry in data:
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not all(isinstance(v, str) for v in entry)
        ):
            raise ValueError("Invalid compile queue entry")
        app, name = entry
        validate_name(app)
        validate_name(name)
        result.append((app, name))
    return result


def compile_pending(
    connection: OpenRoadConnection, root: Path, operation: Path
) -> list[str]:
    path = root / ".openroad/compile-pending.json"
    if not path.exists():
        return []
    try:
        targets = read_compile_queue(path)
    except (ValueError, TypeError, ProjectError) as ex:
        return [
            f"Source sync is complete; cannot read compile queue: {ex}. Run gorak compile explicitly."
        ]
    diagnostics = []
    failed = []
    for app, name in targets:
        try:
            result = compile_source(
                connection, app, name, operation / "compiles" / app / f"{name}.log"
            )
            if not result.success:
                failed.append((app, name))
                diagnostics.append(
                    f"{name}.w4gl failed compilation; run `gorak compile {app} {name}` to see the full error log. Saved log: {result.log}"
                )
        except Exception as ex:
            failed.append((app, name))
            diagnostics.append(
                f"Compilation could not run for {name}.w4gl: {ex}. Run `gorak compile {app} {name}`. Source sync is complete."
            )
    from .push_retry import write_record

    if failed:
        write_record(path, [list(t) for t in failed])
    else:
        path.unlink()
    return diagnostics


def finish_push_compilation(
    connection: OpenRoadConnection, root: Path, operation: Path, summary: str
) -> str:
    """Signal unsuccessful compilation without changing completed source tracking."""
    try:
        diagnostics = compile_pending(connection, root, operation)
    except (OSError, ProjectError) as ex:
        raise PostPushCompilationError(
            f"{summary}\nSource sync is complete; compilation status could not be saved: {ex}"
        ) from ex
    if diagnostics:
        raise PostPushCompilationError(
            "\n".join(
                [
                    summary,
                    "Source sync is complete; compilation did not succeed.",
                    *diagnostics,
                ]
            )
        )
    return summary

"""SSH/SCP wrappers for running Gorak helper scripts on a Windows host."""

import json
import os
import subprocess
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .database import ComponentSyncMetadata
from .domain import Application, ComponentInfo, IncludedApplication
from .sql_output import (
    parse_app_list_output,
    parse_component_list_output,
    parse_component_sync_metadata_output,
    parse_include_list_output,
)

_control_path: str | None = None


@contextmanager
def ssh_session() -> Iterator[None]:
    """Reuse one authenticated transport within a CLI invocation on POSIX hosts."""
    global _control_path
    if os.name != "posix" or _control_path is not None:
        yield
        return
    with TemporaryDirectory(prefix="gorak-ssh-") as directory:
        _control_path = str(Path(directory) / "%C")
        try:
            yield
        finally:
            _control_path = None


def session_command(command: list[str]) -> list[str]:
    if _control_path is None or not command or command[0] not in {"ssh", "scp"}:
        return command
    return [
        command[0],
        "-o",
        "ControlMaster=auto",
        "-o",
        "ControlPersist=10",
        "-o",
        f"ControlPath={_control_path}",
        *command[1:],
    ]


@dataclass(frozen=True)
class RemoteHost:
    """A Windows OpenROAD host reachable over SSH."""

    user: str
    host: str
    gorak_root: str
    writer_database: str | None = None
    writer_encoding: str = "cp1252"

    @property
    def ssh_target(self) -> str:
        return f"{self.user}@{self.host}"


RunCommand = Callable[[list[str]], str]
REMOTE_HELPER_MANIFEST = "gorak-helpers.json"
REMOTE_HELPER_VERSION = "9"
REMOTE_HELPER_FILES = [
    "applist.sql",
    "revision-generation.sql",
    "get-revision-generation.bat",
    "backup-application.bat",
    "backup-component.bat",
    "import-component.bat",
    "compile-source.bat",
    "create-source.bat",
    "update-application.bat",
    "run-application.ps1",
    "writer-command.bat",
    "gorak-writer.pyz",
    "get-app-list.bat",
    "get-component-list.bat",
    "get-component-sync-metadata.bat",
    "get-include-list.bat",
    REMOTE_HELPER_MANIFEST,
]
MISSING_REMOTE_HELPERS = "__GORAK_HELPERS_MISSING__"


class RemoteCommandError(RuntimeError):
    """Raised when a remote command fails."""


def build_remote_command(remote: RemoteHost, script: str, args: list[str]) -> list[str]:
    """Build an SSH command that runs a gorak helper script remotely."""

    remote_script = f"{remote.gorak_root}\\{script}"
    from .writer_launch import remote_writer_prefix

    remote_command = (
        remote_writer_prefix(remote.writer_database, remote.writer_encoding)
        + f"{remote_script} {' '.join(args)}"
    )

    return ["ssh", "-T", remote.ssh_target, remote_command]


def build_download_command(
    remote: RemoteHost, remote_path: str, local_path: str
) -> list[str]:
    """Build an SCP command that downloads a remote file."""

    return ["scp", f"{remote.ssh_target}:{remote_path}", local_path]


def build_upload_command(
    remote: RemoteHost, local_path: str, remote_path: str
) -> list[str]:
    """Build an SCP command that uploads a local file."""

    return [
        "scp",
        local_path,
        f"{remote.ssh_target}:{windows_path_to_scp_path(remote_path)}",
    ]


def build_make_remote_dir_command(remote: RemoteHost) -> list[str]:
    """Build an SSH command that creates the remote gorak root if needed."""

    command = f'if not exist "{remote.gorak_root}" mkdir "{remote.gorak_root}"'
    return ["ssh", "-T", remote.ssh_target, command]


def build_read_remote_manifest_command(remote: RemoteHost) -> list[str]:
    """Build an SSH command that prints the installed helper manifest."""

    manifest_path = f"{remote.gorak_root}\\{REMOTE_HELPER_MANIFEST}"
    command = (
        f'if exist "{manifest_path}" '
        f'(type "{manifest_path}") else (echo {MISSING_REMOTE_HELPERS})'
    )
    return ["ssh", "-T", remote.ssh_target, command]


def windows_path_to_scp_path(path: str) -> str:
    """Convert a Windows path to the format expected by SCP."""

    return f"/{path.replace('\\', '/')}"


def run_subprocess(command: list[str]) -> str:
    """Run a command and return stdout."""

    try:
        result = subprocess.run(
            session_command(command),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as ex:
        output = "\n".join(text.strip() for text in [ex.stdout, ex.stderr] if text)
        raise RemoteCommandError(
            f"Remote command failed with exit code {ex.returncode}\n{output}"
        ) from ex

    return result.stdout


def download_file(
    remote: RemoteHost,
    remote_path: str,
    local_path: str,
    run_cmd: RunCommand = run_subprocess,
) -> str:
    """Download a remote Windows file path and return the local path."""

    scp_path = windows_path_to_scp_path(remote_path)
    command = build_download_command(remote, scp_path, local_path)
    run_cmd(command)
    return local_path


def install_remote_helpers(
    remote: RemoteHost,
    helper_files: Sequence[Path],
    run_cmd: RunCommand = run_subprocess,
) -> list[str]:
    """Install local Windows helper files into the remote gorak root."""

    files = sorted(
        helper_files, key=lambda path: (path.name == REMOTE_HELPER_MANIFEST, path.name)
    )
    run_cmd(build_make_remote_dir_command(remote))

    for path in files:
        run_cmd(
            build_upload_command(
                remote=remote,
                local_path=str(path),
                remote_path=f"{remote.gorak_root}\\{path.name}",
            )
        )

    return [path.name for path in files]


def verify_remote_helpers(
    remote: RemoteHost,
    run_cmd: RunCommand = run_subprocess,
) -> None:
    """Verify packaged helpers are installed on the remote host."""

    output = run_cmd(build_read_remote_manifest_command(remote)).strip()
    if output == MISSING_REMOTE_HELPERS:
        raise RemoteCommandError(remote_helper_error())

    try:
        manifest = json.loads(output)
    except json.JSONDecodeError as ex:
        raise RemoteCommandError(remote_helper_error()) from ex

    if (
        manifest.get("version") != REMOTE_HELPER_VERSION
        or manifest.get("files") != REMOTE_HELPER_FILES
    ):
        raise RemoteCommandError(remote_helper_error())


def remote_helper_error() -> str:
    return (
        "Remote helpers are missing or outdated. "
        "Run `gorak remote install` and try again."
    )


def backup_component(
    remote: RemoteHost,
    vnode: str,
    database: str,
    app: str,
    component: str,
    run_cmd: RunCommand = run_subprocess,
) -> str:
    """Export a component on the remote host and return the remote XML path."""

    if remote.writer_database:
        verify_remote_helpers(remote, run_cmd)

    command = build_remote_command(
        remote=remote,
        script="backup-component.bat",
        args=[f"{vnode}::{database}", app, component],
    )

    output = run_cmd(command).strip()
    return last_output_line(output)


def backup_application(
    remote: RemoteHost,
    vnode: str,
    database: str,
    app: str,
    run_cmd: RunCommand = run_subprocess,
) -> str:
    """Export a full application on the remote host and return the remote XML path."""

    if remote.writer_database:
        verify_remote_helpers(remote, run_cmd)

    command = build_remote_command(
        remote=remote,
        script="backup-application.bat",
        args=[f"{vnode}::{database}", app],
    )

    return last_output_line(run_cmd(command).strip())


def last_output_line(output: str) -> str:
    """Return the last line from command output."""

    return output.splitlines()[-1]


def get_app_list(
    remote: RemoteHost,
    vnode: str,
    database: str,
    run_cmd: RunCommand = run_subprocess,
) -> list[Application]:
    """Read OpenROAD application metadata from the remote source database."""

    command = build_remote_command(
        remote=remote,
        script="get-app-list.bat",
        args=[vnode, database],
    )

    return parse_app_list_output(run_cmd(command))


def get_component_list(
    remote: RemoteHost,
    vnode: str,
    database: str,
    app: str,
    run_cmd: RunCommand = run_subprocess,
) -> list[ComponentInfo]:
    """Read OpenROAD component metadata from a remote source database."""

    command = build_remote_command(
        remote=remote,
        script="get-component-list.bat",
        args=[vnode, database, app],
    )

    return parse_component_list_output(run_cmd(command))


def get_include_list(
    remote: RemoteHost,
    vnode: str,
    database: str,
    app: str,
    run_cmd: RunCommand = run_subprocess,
) -> list[IncludedApplication]:
    """Read ordered included application metadata from a remote source database."""

    command = build_remote_command(
        remote=remote,
        script="get-include-list.bat",
        args=[vnode, database, app],
    )

    return parse_include_list_output(run_cmd(command))


def get_all_component_sync_metadata(
    remote: RemoteHost,
    vnode: str,
    database: str,
    run_cmd: RunCommand = run_subprocess,
) -> list[ComponentSyncMetadata]:
    """Read component change metadata for all applications remotely."""

    command = build_remote_command(
        remote=remote,
        script="get-component-sync-metadata.bat",
        args=[vnode, database],
    )

    return parse_component_sync_metadata_output(run_cmd(command))

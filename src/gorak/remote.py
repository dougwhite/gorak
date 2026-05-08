import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .domain import Application, ComponentInfo
from .sql_output import parse_app_list_output, parse_component_list_output


@dataclass(frozen=True)
class RemoteHost:
    """A Windows OpenROAD host reachable over SSH."""

    user: str
    host: str
    gorak_root: str

    @property
    def ssh_target(self) -> str:
        return f"{self.user}@{self.host}"


RunCommand = Callable[[list[str]], str]


class RemoteCommandError(RuntimeError):
    """Raised when a remote command fails."""


def build_remote_command(remote: RemoteHost, script: str, args: list[str]) -> list[str]:
    """Build an SSH command that runs a gorak helper script remotely."""

    remote_script = f"{remote.gorak_root}\\{script}"
    remote_command = f"{remote_script} {' '.join(args)}"

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


def windows_path_to_scp_path(path: str) -> str:
    """Convert a Windows path to the format expected by SCP."""

    return f"/{path.replace('\\', '/')}"


def run_subprocess(command: list[str]) -> str:
    """Run a command and return stdout."""

    try:
        result = subprocess.run(
            command,
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

    files = sorted(helper_files, key=lambda path: path.name)
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


def backup_component(
    remote: RemoteHost,
    vnode: str,
    database: str,
    app: str,
    component: str,
    run_cmd: RunCommand = run_subprocess,
) -> str:
    """Export a component on the remote host and return the remote XML path."""

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

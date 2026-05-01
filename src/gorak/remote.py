import subprocess
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteHost:
    """Represents a remote host that can be connected to via ssh"""
    ssh_target: str
    gorak_root: str

RunCommand = Callable[[list[str]], str]

class RemoteCommandError(RuntimeError):
    """Raised when a remote command fails."""


def build_remote_command(remote: RemoteHost, script: str, args: list[str]) -> list[str]:
    """Constructs an ssh command from a list of arguments, returns as a list of command segments"""
    
    remote_script = f"{remote.gorak_root}\\{script}"
    remote_command = f"{remote_script} {' '.join(args)}"
    
    return ["ssh", "-T", remote.ssh_target, remote_command]

def build_download_command(remote: RemoteHost, remote_path: str, local_path: str) -> list[str]:
    """Constructs an scp command to download a remote file to a local path"""

    return ["scp", f"{remote.ssh_target}:{remote_path}", local_path]

def windows_path_to_scp_path(path: str) -> str:
    """Converts a Windows path to the format expected by scp"""

    return f"/{path.replace('\\', '/')}"

def run_subprocess(command: list[str]) -> str:
    """Runs a command using subprocess and returns the stdout as a string"""
    
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as ex:
        output = "\n".join(
            text.strip()
            for text in [ex.stdout, ex.stderr]
            if text
        )
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
    """Downloads a remote Windows file path over scp and returns the local path"""

    scp_path = windows_path_to_scp_path(remote_path)
    command = build_download_command(remote, scp_path, local_path)
    run_cmd(command)
    return local_path

def backup_component(remote: RemoteHost, vnode: str, database: str, app: str, component: str, run_cmd: RunCommand = run_subprocess) -> str:
    """Backs up a component from the remote host and returns the path to the backup file"""
    
    command = build_remote_command(
        remote=remote,
        script="backup-component.bat",
        args=[f"{vnode}::{database}", app, component]
    )
    
    output = run_cmd(command).strip()
    return output.splitlines()[-1]

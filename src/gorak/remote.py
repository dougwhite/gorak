import subprocess
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteHost:
    """Represents a remote host that can be connected to via ssh"""
    ssh_target: str
    gorak_root: str

RunCommand = Callable[[list[str]], str]

def build_remote_command(remote: RemoteHost, script: str, args: list[str]) -> list[str]:
    """Constructs an ssh command from a list of arguments, returns as a list of command segments"""
    
    remote_script = f"{remote.gorak_root}\\{script}"
    remote_command = f"{remote_script} {' '.join(args)}"
    
    return ["ssh", "-T", remote.ssh_target, remote_command]

def run_subprocess(command: list[str]) -> str:
    """Runs a command using subprocess and returns the stdout as a string"""
    
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout

def backup_component(remote: RemoteHost, vnode: str, database: str, app: str, component: str, run_cmd: RunCommand = run_subprocess) -> str:
    """Backs up a component from the remote host and returns the path to the backup file"""
    
    command = build_remote_command(
        remote=remote,
        script="backup-component.bat",
        args=[f"{vnode}::{database}", app, component]
    )
    
    return run_cmd(command).strip()

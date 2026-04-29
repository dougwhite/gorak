from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteHost:
    """Represents a remote host that can be connected to via ssh"""
    ssh_target: str
    gorak_root: str

def build_remote_command(remote: RemoteHost, script: str, args: list[str]) -> list[str]:
    """Constructs an ssh command from a list of arguments, returns as a list of command segments"""
    
    remote_script = f"{remote.gorak_root}\\{script}"
    remote_command = f"{remote_script} {' '.join(args)}"
    
    return ["ssh", "-T", remote.ssh_target, remote_command]
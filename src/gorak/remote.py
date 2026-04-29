def build_remote_command(user: str, host: str, gorak_root: str, script: str, args: list[str]) -> list[str]:
    """Constructs an ssh command from a list of arguments, returns as a list of command segments"""
    
    ssh_target = f"{user}@{host}"
    remote_script = f"{gorak_root}\\{script}"
    remote_command = f"{remote_script} {' '.join(args)}"
    
    return ["ssh", "-T", ssh_target, remote_command]
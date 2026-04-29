from gorak.remote import RemoteHost, build_remote_command

REMOTE_HOST = RemoteHost(
    ssh_target="test@WINDOWS-PC",
    gorak_root=r"c:\Development\gorak"
)

class TestBuildRemoteCommand:
    """Tests for the build_remote_command() function"""
    
    def test_returns_a_list_of_strings(self) -> None:
        command = build_remote_command(
            remote=REMOTE_HOST,
            script="backup-component.bat",
            args=["vnode::db", "app", "component"]
        )
        
        assert command == [
            "ssh",
            "-T",
            "test@WINDOWS-PC",
            r"c:\Development\gorak\backup-component.bat vnode::db app component"
        ]
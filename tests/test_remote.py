from gorak.remote import build_remote_command


class TestBuildRemoteCommand:
    """Tests for the build_remote_command() function"""
    
    def test_returns_a_list_of_strings(self) -> None:
        command = build_remote_command(
            user="test",
            host="WINDOWS-PC",
            gorak_root=r"c:\Development\gorak",
            script="backup-component.bat",
            args=["vnode::db", "app", "component"]
        )
        
        assert command == [
            "ssh",
            "-T",
            "test@WINDOWS-PC",
            r"c:\Development\gorak\backup-component.bat vnode::db app component"
        ]
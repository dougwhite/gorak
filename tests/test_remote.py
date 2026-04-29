from gorak.remote import RemoteHost, backup_component, build_remote_command

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

class TestBackupComponent:
    """Tests for the backup_component() function"""
    
    def test_backup_component_runs_remote_command(self) -> None:
        calls = []
        
        def fake_run(command: list[str]) -> str:
            calls.append(command)
            return r"C:\Development\gorak\repos\vnode\db\app\component.xml"
        
        result = backup_component(
            remote=REMOTE_HOST,
            vnode="vnode",
            database="db",
            app="app",
            component="component",
            run_cmd=fake_run
        )
        
        assert result == r"C:\Development\gorak\repos\vnode\db\app\component.xml"
        assert calls == [
            [
                "ssh",
                "-T",
                "test@WINDOWS-PC",
                r"c:\Development\gorak\backup-component.bat vnode::db app component"
            ]
        ]
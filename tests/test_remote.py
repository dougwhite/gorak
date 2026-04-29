import subprocess

import pytest

from gorak.remote import (
    RemoteCommandError,
    RemoteHost,
    backup_component,
    build_download_command,
    build_remote_command,
    run_subprocess,
)

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

class TestBuildDownloadCommand:
    """Tests for the build_download_command() function"""

    def test_returns_an_scp_command_for_downloading_a_remote_file(self) -> None:
        command = build_download_command(
            remote=REMOTE_HOST,
            remote_path="/C:/Development/gorak/repos/vnode/db/app/component.xml",
            local_path="component.xml",
        )

        assert command == [
            "scp",
            "test@WINDOWS-PC:/C:/Development/gorak/repos/vnode/db/app/component.xml",
            "component.xml",
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

    def test_uses_subprocess_runner_by_default(self, monkeypatch) -> None:
        calls = []

        def fake_run(
            command: list[str],
            check: bool,
            capture_output: bool,
            text: bool,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=r"C:\Development\gorak\repos\vnode\db\app\component.xml" + "\n",
                stderr="",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = backup_component(
            remote=REMOTE_HOST,
            vnode="vnode",
            database="db",
            app="app",
            component="component",
        )

        assert result == r"C:\Development\gorak\repos\vnode\db\app\component.xml"
        assert calls == [
            [
                "ssh",
                "-T",
                "test@WINDOWS-PC",
                r"c:\Development\gorak\backup-component.bat vnode::db app component",
            ]
        ]

    def test_returns_only_the_last_output_line(self) -> None:
        def fake_run(command: list[str]) -> str:
            return (
                "** WARNING: connection is not using a post-quantum key exchange algorithm.\n"
                "** This session may be vulnerable to store now, decrypt later attacks.\n"
                r"C:\Development\gorak\repos\vnode\db\app\component.xml"
                "\n"
            )

        result = backup_component(
            remote=REMOTE_HOST,
            vnode="vnode",
            database="db",
            app="app",
            component="component",
            run_cmd=fake_run
        )

        assert result == r"C:\Development\gorak\repos\vnode\db\app\component.xml"

class TestRunSubprocess:
    """Tests for the run_subprocess() function"""

    def test_returns_stdout_from_completed_process(self, monkeypatch) -> None:
        calls = []

        def fake_run(
            command: list[str],
            check: bool,
            capture_output: bool,
            text: bool,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(
                {
                    "command": command,
                    "check": check,
                    "capture_output": capture_output,
                    "text": text,
                }
            )
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="remote output\n",
                stderr="",
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = run_subprocess(["ssh", "-T", "test@WINDOWS-PC", "remote command"])

        assert result == "remote output\n"
        assert calls == [
            {
                "command": ["ssh", "-T", "test@WINDOWS-PC", "remote command"],
                "check": True,
                "capture_output": True,
                "text": True,
            }
        ]

    def test_raises_an_error_when_process_fails(self, monkeypatch) -> None:
        def fake_run(
            command: list[str],
            check: bool,
            capture_output: bool,
            text: bool,
        ) -> subprocess.CompletedProcess[str]:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=command,
                output="ERROR: Cannot fetch component missing_component from database.\n",
                stderr=(
                    "** WARNING: connection is not using a post-quantum key exchange algorithm.\n"
                    "w4gldev failed with exit code 1\n"
                    r'Log: "C:\Users\testuser\AppData\Local\Temp\gorak-export-missing_component-12345.log"'
                    "\n"
                ),
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(RemoteCommandError) as ex:
            run_subprocess(["ssh", "-T", "test@WINDOWS-PC", "remote command"])

        assert "Remote command failed with exit code 1" in str(ex.value)
        assert "Cannot fetch component missing_component" in str(ex.value)
        assert "gorak-export-missing_component-12345.log" in str(ex.value)

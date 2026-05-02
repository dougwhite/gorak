import subprocess
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from gorak.domain import Application, ComponentInfo
from gorak.remote import (
    RemoteCommandError,
    RemoteHost,
    backup_component,
    build_download_command,
    build_make_remote_dir_command,
    build_remote_command,
    build_upload_command,
    download_file,
    get_app_list,
    get_component_list,
    install_remote_helpers,
    parse_app_list_output,
    parse_component_list_output,
    run_subprocess,
    windows_path_to_scp_path,
)

REMOTE_HOST = RemoteHost(
    user="test",
    host="WINDOWS-PC",
    gorak_root=r"c:\Development\gorak",
)

APP_LIST_OUTPUT = """
INGRES TERMINAL MONITOR Copyright 2024 Actian Corporation
continue
* * * * /* SQL Startup File */
select e.entity_name as application_name, a.proc_start as start_component, e.short_remark
from ii_applications a
left join ii_entities e on a.entity_id = e.entity_id
Executing . . .


+--------------------------------+--------------------------------+------------------------------------------------------------+
|application_name                |start_component                 |short_remark                                                |
+--------------------------------+--------------------------------+------------------------------------------------------------+
|sample_app                      |                                |Example application                                         |
|orders_app                      |fm_order_entry                  |Order entry screens                                         |
|shared_library                  |                                |Shared utility components                                   |
|empty_shell                     |                                |                                                            |
+--------------------------------+--------------------------------+------------------------------------------------------------+
(4 rows)

Your SQL statement(s) have been committed.
"""

COMPONENT_LIST_OUTPUT = """
INGRES TERMINAL MONITOR Copyright 2024 Actian Corporation
continue
* * * * * * * * /* SQL Startup File */
select ea.entity_name as application_name, e.entity_name as component_name, e.entity_type, e.short_remark
from ii_entities e
left join ii_entities ea on e.folder_id = ea.entity_id
left join ii_applications a on ea.base_entity_id = a.entity_id
where e.base_entity_id = 0
and e.folder_id != 0
and ea.entity_name = 'sample_app'
Executing . . .


+--------------------------------+--------------------------------+--------------------------------+------------------------------------------------------------+
|application_name                |component_name                  |entity_type                     |short_remark                                                |
+--------------------------------+--------------------------------+--------------------------------+------------------------------------------------------------+
|sample_app                      |uc_order                        |classsource                     |Order model                                                 |
|sample_app                      |p4_check_order                  |proc4glsource                   |                                                            |
|sample_app                      |fm_order_entry                  |framesource                     |Main order entry screen                                     |
+--------------------------------+--------------------------------+--------------------------------+------------------------------------------------------------+
(3 rows)

Your SQL statement(s) have been committed.
"""


class TestBuildRemoteCommand:
    """Tests for the build_remote_command() function"""

    def test_remote_host_derives_ssh_target(self) -> None:
        assert REMOTE_HOST.ssh_target == "test@WINDOWS-PC"

    def test_returns_an_ssh_command_for_calling_a_gorak_script(self) -> None:
        command = build_remote_command(
            remote=REMOTE_HOST,
            script="backup-component.bat",
            args=["vnode::db", "app", "component"],
        )

        assert command == [
            "ssh",
            "-T",
            "test@WINDOWS-PC",
            r"c:\Development\gorak\backup-component.bat vnode::db app component",
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


class TestBuildUploadCommand:
    """Tests for the build_upload_command() function."""

    def test_returns_an_scp_command_for_uploading_a_remote_file(self) -> None:
        command = build_upload_command(
            remote=REMOTE_HOST,
            local_path="src/gorak/remote_scripts/backup-component.bat",
            remote_path=r"c:\Development\gorak\backup-component.bat",
        )

        assert command == [
            "scp",
            "src/gorak/remote_scripts/backup-component.bat",
            "test@WINDOWS-PC:/c:/Development/gorak/backup-component.bat",
        ]


class TestBuildMakeRemoteDirCommand:
    """Tests for the build_make_remote_dir_command() function."""

    def test_returns_an_ssh_command_for_creating_the_remote_root(self) -> None:
        command = build_make_remote_dir_command(REMOTE_HOST)

        assert command == [
            "ssh",
            "-T",
            "test@WINDOWS-PC",
            r'if not exist "c:\Development\gorak" mkdir "c:\Development\gorak"',
        ]


class TestWindowsPathToScpPath:
    """Tests for the windows_path_to_scp_path() function"""

    def test_converts_windows_path_to_scp_path(self) -> None:
        result = windows_path_to_scp_path(
            r"C:\Development\gorak\repos\vnode\db\app\component.xml"
        )

        assert result == "/C:/Development/gorak/repos/vnode/db/app/component.xml"


class TestDownloadFile:
    """Tests for the download_file() function"""

    def test_downloads_remote_file_to_local_path(self) -> None:
        calls = []

        def fake_run(command: list[str]) -> str:
            calls.append(command)
            return ""

        result = download_file(
            remote=REMOTE_HOST,
            remote_path=r"C:\Development\gorak\repos\vnode\db\app\component.xml",
            local_path="component.xml",
            run_cmd=fake_run,
        )

        assert result == "component.xml"
        assert calls == [
            [
                "scp",
                "test@WINDOWS-PC:/C:/Development/gorak/repos/vnode/db/app/component.xml",
                "component.xml",
            ]
        ]


class TestInstallRemoteHelpers:
    """Tests for installing Windows helper files to a remote gorak root."""

    def test_installs_each_helper_file_to_the_remote_root(self, tmp_path: Path) -> None:
        source_dir = tmp_path / "remote_scripts"
        source_dir.mkdir()
        (source_dir / "README.md").write_text("docs")
        (source_dir / "backup-component.bat").write_text("@echo off")
        (source_dir / "applist.sql").write_text("select 1")
        (source_dir / "ignored").mkdir()
        calls = []

        def fake_run(command: list[str]) -> str:
            calls.append(command)
            return ""

        result = install_remote_helpers(
            remote=REMOTE_HOST,
            helper_files=[
                source_dir / "README.md",
                source_dir / "backup-component.bat",
                source_dir / "applist.sql",
            ],
            run_cmd=fake_run,
        )

        assert result == ["README.md", "applist.sql", "backup-component.bat"]
        assert calls == [
            [
                "ssh",
                "-T",
                "test@WINDOWS-PC",
                r'if not exist "c:\Development\gorak" mkdir "c:\Development\gorak"',
            ],
            [
                "scp",
                str(source_dir / "README.md"),
                "test@WINDOWS-PC:/c:/Development/gorak/README.md",
            ],
            [
                "scp",
                str(source_dir / "applist.sql"),
                "test@WINDOWS-PC:/c:/Development/gorak/applist.sql",
            ],
            [
                "scp",
                str(source_dir / "backup-component.bat"),
                "test@WINDOWS-PC:/c:/Development/gorak/backup-component.bat",
            ],
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
            run_cmd=fake_run,
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

    def test_uses_subprocess_runner_by_default(self, monkeypatch: MonkeyPatch) -> None:
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
            run_cmd=fake_run,
        )

        assert result == r"C:\Development\gorak\repos\vnode\db\app\component.xml"


class TestParseAppListOutput:
    """Tests for parsing Ingres application list output."""

    def test_parses_application_rows_from_terminal_monitor_output(self) -> None:
        assert parse_app_list_output(APP_LIST_OUTPUT) == [
            Application(
                name="sample_app",
                start_component="",
                description="Example application",
            ),
            Application(
                name="orders_app",
                start_component="fm_order_entry",
                description="Order entry screens",
            ),
            Application(
                name="shared_library",
                start_component="",
                description="Shared utility components",
            ),
            Application(name="empty_shell", start_component="", description=""),
        ]


class TestGetAppList:
    """Tests for the get_app_list() function."""

    def test_runs_remote_get_app_list_command(self) -> None:
        calls = []

        def fake_run(command: list[str]) -> str:
            calls.append(command)
            return APP_LIST_OUTPUT

        result = get_app_list(
            remote=REMOTE_HOST,
            vnode="vnode",
            database="db",
            run_cmd=fake_run,
        )

        assert result[0] == Application(
            name="sample_app",
            start_component="",
            description="Example application",
        )
        assert calls == [
            [
                "ssh",
                "-T",
                "test@WINDOWS-PC",
                r"c:\Development\gorak\get-app-list.bat vnode db",
            ]
        ]


class TestParseComponentListOutput:
    """Tests for parsing Ingres component list output."""

    def test_parses_component_rows_from_terminal_monitor_output(self) -> None:
        assert parse_component_list_output(COMPONENT_LIST_OUTPUT) == [
            ComponentInfo(
                application_name="sample_app",
                name="uc_order",
                type="classsource",
                description="Order model",
            ),
            ComponentInfo(
                application_name="sample_app",
                name="p4_check_order",
                type="proc4glsource",
                description="",
            ),
            ComponentInfo(
                application_name="sample_app",
                name="fm_order_entry",
                type="framesource",
                description="Main order entry screen",
            ),
        ]


class TestGetComponentList:
    """Tests for the get_component_list() function."""

    def test_runs_remote_get_component_list_command(self) -> None:
        calls = []

        def fake_run(command: list[str]) -> str:
            calls.append(command)
            return COMPONENT_LIST_OUTPUT

        result = get_component_list(
            remote=REMOTE_HOST,
            vnode="vnode",
            database="db",
            app="sample_app",
            run_cmd=fake_run,
        )

        assert result[0] == ComponentInfo(
            application_name="sample_app",
            name="uc_order",
            type="classsource",
            description="Order model",
        )
        assert calls == [
            [
                "ssh",
                "-T",
                "test@WINDOWS-PC",
                r"c:\Development\gorak\get-component-list.bat vnode db sample_app",
            ]
        ]


class TestRunSubprocess:
    """Tests for the run_subprocess() function"""

    def test_returns_stdout_from_completed_process(
        self, monkeypatch: MonkeyPatch
    ) -> None:
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

    def test_raises_an_error_when_process_fails(self, monkeypatch: MonkeyPatch) -> None:
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

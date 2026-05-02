import json
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak.domain import Application, ComponentInfo
from gorak.project import GorakProject
from gorak.remote import RemoteHost

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "fm_example_frame.xml"


class TestComponentExport:
    """Tests for the component export CLI command."""

    def test_exports_component_to_project_cache_and_source(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        (project_root / ".env").write_text(
            "GORAK_BACKEND=remote\n"
            "GORAK_REMOTE_USER=project-user\n"
            "GORAK_REMOTE_HOST=project-host\n"
            "GORAK_REMOTE_ROOT=C:\\Development\\gorak\n"
            "GORAK_VNODE=project-vnode\n"
            "GORAK_DATABASE=project-db\n"
        )
        monkeypatch.chdir(project_root)

        def fake_backup_component(
            remote: RemoteHost,
            vnode: str,
            database: str,
            app: str,
            component: str,
        ) -> str:
            calls.append(("backup", remote, vnode, database, app, component))
            return r"C:\Development\gorak\repos\vnode\db\app\component.xml"

        def fake_download_file(
            remote: RemoteHost,
            remote_path: str,
            local_path: str,
        ) -> str:
            calls.append(("download", remote, remote_path, local_path))
            Path(local_path).write_text(FIXTURE_PATH.read_text())
            return local_path

        monkeypatch.setattr(cli, "backup_component", fake_backup_component)
        monkeypatch.setattr(cli, "download_file", fake_download_file)

        cli.main(
            [
                "component",
                "export",
                "app",
                "component",
            ]
        )

        remote = RemoteHost(
            user="project-user",
            host="project-host",
            gorak_root=r"C:\Development\gorak",
        )
        xml_path = project_root / ".openroad" / "app" / "component.xml"
        w4gl_path = project_root / "app" / "component.w4gl"
        assert calls == [
            ("backup", remote, "project-vnode", "project-db", "app", "component"),
            (
                "download",
                remote,
                r"C:\Development\gorak\repos\vnode\db\app\component.xml",
                str(xml_path),
            ),
        ]
        assert xml_path.read_text() == FIXTURE_PATH.read_text()
        assert "[framesource]" in w4gl_path.read_text()
        assert "initialize()=" in w4gl_path.read_text()
        assert capsys.readouterr().out == f"{w4gl_path}\n"

    def test_overwrites_existing_project_files(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        xml_path = project_root / ".openroad" / "app" / "component.xml"
        w4gl_path = project_root / "app" / "component.w4gl"
        xml_path.parent.mkdir(parents=True)
        w4gl_path.parent.mkdir(parents=True)
        xml_path.write_text("old xml")
        w4gl_path.write_text("old w4gl")
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        (project_root / ".env").write_text(
            "GORAK_BACKEND=remote\n"
            "GORAK_REMOTE_USER=project-user\n"
            "GORAK_REMOTE_HOST=project-host\n"
            "GORAK_REMOTE_ROOT=C:\\Development\\gorak\n"
            "GORAK_VNODE=project-vnode\n"
            "GORAK_DATABASE=project-db\n"
        )
        monkeypatch.chdir(project_root)
        monkeypatch.setattr(
            cli,
            "backup_component",
            lambda remote, vnode, database, app, component: r"C:\remote\component.xml",
        )

        def fake_download_file(
            remote: RemoteHost,
            remote_path: str,
            local_path: str,
        ) -> str:
            Path(local_path).write_text(FIXTURE_PATH.read_text())
            return local_path

        monkeypatch.setattr(cli, "download_file", fake_download_file)

        cli.main(["component", "export", "app", "component"])

        assert xml_path.read_text() == FIXTURE_PATH.read_text()
        assert w4gl_path.read_text() != "old w4gl"
        assert "[framesource]" in w4gl_path.read_text()
        assert capsys.readouterr().out == f"{w4gl_path}\n"

    def test_requires_output_outside_project(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as ex:
            cli.main(
                [
                    "component",
                    "export",
                    "--user",
                    "test",
                    "--host",
                    "WINDOWS-PC",
                    "--gorak-root",
                    r"c:\Development\gorak",
                    "--vnode",
                    "vnode",
                    "--database",
                    "db",
                    "app",
                    "component",
                ]
            )

        assert ex.value.code == 1
        assert "--output is required outside a gorak project" in capsys.readouterr().err

    def test_exports_to_output_path_outside_project(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        download_paths: list[str] = []
        monkeypatch.chdir(tmp_path)
        output_path = tmp_path / "component.w4gl"

        def fake_backup_component(
            remote: RemoteHost,
            vnode: str,
            database: str,
            app: str,
            component: str,
        ) -> str:
            calls.append(("backup", remote, vnode, database, app, component))
            return r"C:\Development\gorak\repos\vnode\db\app\component.xml"

        def fake_download_file(
            remote: RemoteHost,
            remote_path: str,
            local_path: str,
        ) -> str:
            calls.append(("download", remote, remote_path, local_path))
            download_paths.append(local_path)
            assert Path(local_path).parent != tmp_path
            Path(local_path).write_text(FIXTURE_PATH.read_text())
            return local_path

        monkeypatch.setattr(cli, "backup_component", fake_backup_component)
        monkeypatch.setattr(cli, "download_file", fake_download_file)

        cli.main(
            [
                "component",
                "export",
                "--user",
                "test",
                "--host",
                "WINDOWS-PC",
                "--gorak-root",
                r"c:\Development\gorak",
                "--vnode",
                "vnode",
                "--database",
                "db",
                "--output",
                str(output_path),
                "app",
                "component",
            ]
        )

        remote = RemoteHost(
            user="test",
            host="WINDOWS-PC",
            gorak_root=r"c:\Development\gorak",
        )
        assert calls[0] == ("backup", remote, "vnode", "db", "app", "component")
        assert calls[1] == (
            "download",
            remote,
            r"C:\Development\gorak\repos\vnode\db\app\component.xml",
            download_paths[0],
        )
        assert output_path.is_file()
        assert "[framesource]" in output_path.read_text()
        assert capsys.readouterr().out == f"{output_path}\n"

    def test_rejects_output_inside_project(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        (project_root / ".env").write_text(
            "GORAK_BACKEND=remote\n"
            "GORAK_REMOTE_USER=project-user\n"
            "GORAK_REMOTE_HOST=project-host\n"
            "GORAK_REMOTE_ROOT=C:\\Development\\gorak\n"
            "GORAK_VNODE=project-vnode\n"
            "GORAK_DATABASE=project-db\n"
        )
        monkeypatch.chdir(project_root)

        with pytest.raises(SystemExit) as ex:
            cli.main(
                [
                    "component",
                    "export",
                    "--output",
                    "component.w4gl",
                    "app",
                    "component",
                ]
            )

        assert ex.value.code == 1
        assert "--output is only supported outside a gorak project" in (
            capsys.readouterr().err
        )

    def test_old_app_and_component_flags_are_not_supported(
        self, capsys: CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as ex:
            cli.main(
                [
                    "component",
                    "export",
                    "--app",
                    "app",
                    "--component",
                    "component",
                ]
            )

        assert ex.value.code == 2
        assert "unrecognized arguments: --app --component" in capsys.readouterr().err


class TestAppList:
    """Tests for the app list CLI command."""

    def test_prints_json_by_default(
        self,
        monkeypatch: MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []

        def fake_get_app_list(
            remote: RemoteHost,
            vnode: str,
            database: str,
        ) -> list[Application]:
            calls.append(("get_app_list", remote, vnode, database))
            return [
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
            ]

        monkeypatch.setattr(cli, "get_app_list", fake_get_app_list)

        cli.main(
            [
                "app",
                "list",
                "--user",
                "test",
                "--host",
                "WINDOWS-PC",
                "--gorak-root",
                r"c:\Development\gorak",
                "--vnode",
                "vnode",
                "--database",
                "db",
            ]
        )

        remote = RemoteHost(
            user="test",
            host="WINDOWS-PC",
            gorak_root=r"c:\Development\gorak",
        )
        assert calls == [("get_app_list", remote, "vnode", "db")]
        assert json.loads(capsys.readouterr().out) == [
            {
                "name": "sample_app",
                "start_component": "",
                "description": "Example application",
            },
            {
                "name": "orders_app",
                "start_component": "fm_order_entry",
                "description": "Order entry screens",
            },
        ]

    def test_prints_csv_when_requested(
        self,
        monkeypatch: MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        def fake_get_app_list(
            remote: RemoteHost,
            vnode: str,
            database: str,
        ) -> list[Application]:
            return [
                Application(
                    name="sample_app",
                    start_component="",
                    description="Example application",
                )
            ]

        monkeypatch.setattr(cli, "get_app_list", fake_get_app_list)

        cli.main(
            [
                "app",
                "list",
                "--user",
                "test",
                "--host",
                "WINDOWS-PC",
                "--gorak-root",
                r"c:\Development\gorak",
                "--vnode",
                "vnode",
                "--database",
                "db",
                "--format",
                "csv",
            ]
        )

        assert capsys.readouterr().out == (
            "name,start_component,description\nsample_app,,Example application\n"
        )

    def test_rejects_invalid_format(self, capsys: CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as ex:
            cli.main(
                [
                    "app",
                    "list",
                    "--user",
                    "test",
                    "--host",
                    "WINDOWS-PC",
                    "--gorak-root",
                    r"c:\Development\gorak",
                    "--vnode",
                    "vnode",
                    "--database",
                    "db",
                    "--format",
                    "toml",
                ]
            )

        assert ex.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_requires_remote_flags(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        for key in [
            "GORAK_REMOTE_USER",
            "GORAK_REMOTE_HOST",
            "GORAK_REMOTE_ROOT",
            "GORAK_VNODE",
            "GORAK_DATABASE",
        ]:
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(SystemExit) as ex:
            cli.main(["app", "list"])

        assert ex.value.code == 1
        assert "Missing OpenROAD connection settings" in capsys.readouterr().err

    def test_reads_connection_settings_from_project_env(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        project_root = tmp_path / "my_project"
        app_dir = project_root / "my_project"
        app_dir.mkdir(parents=True)
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        (project_root / ".env").write_text(
            "GORAK_BACKEND=remote\n"
            "GORAK_REMOTE_USER=project-user\n"
            "GORAK_REMOTE_HOST=project-host\n"
            "GORAK_REMOTE_ROOT=C:\\Development\\gorak\n"
            "GORAK_VNODE=project-vnode\n"
            "GORAK_DATABASE=project-db\n"
        )
        monkeypatch.chdir(app_dir)

        def fake_get_app_list(
            remote: RemoteHost,
            vnode: str,
            database: str,
        ) -> list[Application]:
            calls.append(("get_app_list", remote, vnode, database))
            return []

        monkeypatch.setattr(cli, "get_app_list", fake_get_app_list)

        cli.main(["app", "list"])

        assert calls == [
            (
                "get_app_list",
                RemoteHost(
                    user="project-user",
                    host="project-host",
                    gorak_root=r"C:\Development\gorak",
                ),
                "project-vnode",
                "project-db",
            )
        ]
        assert json.loads(capsys.readouterr().out) == []

    def test_flags_override_project_env(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        (project_root / ".env").write_text(
            "GORAK_BACKEND=remote\n"
            "GORAK_REMOTE_USER=project-user\n"
            "GORAK_REMOTE_HOST=project-host\n"
            "GORAK_REMOTE_ROOT=C:\\Development\\gorak\n"
            "GORAK_VNODE=project-vnode\n"
            "GORAK_DATABASE=project-db\n"
        )
        monkeypatch.chdir(project_root)

        def fake_get_app_list(
            remote: RemoteHost,
            vnode: str,
            database: str,
        ) -> list[Application]:
            calls.append(("get_app_list", remote, vnode, database))
            return []

        monkeypatch.setattr(cli, "get_app_list", fake_get_app_list)

        cli.main(
            [
                "app",
                "list",
                "--user",
                "flag-user",
                "--host",
                "flag-host",
                "--gorak-root",
                r"C:\Flag\gorak",
                "--vnode",
                "flag-vnode",
                "--database",
                "flag-db",
            ]
        )

        assert calls == [
            (
                "get_app_list",
                RemoteHost(
                    user="flag-user",
                    host="flag-host",
                    gorak_root=r"C:\Flag\gorak",
                ),
                "flag-vnode",
                "flag-db",
            )
        ]
        assert json.loads(capsys.readouterr().out) == []

    def test_remote_app_list_command_is_not_supported(
        self, capsys: CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as ex:
            cli.main(["remote", "get-app-list"])

        assert ex.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_remote_export_component_command_is_not_supported(
        self, capsys: CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as ex:
            cli.main(["remote", "export-component"])

        assert ex.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_errors_when_backend_is_not_implemented(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        (project_root / ".env").write_text("GORAK_BACKEND=local\n")
        monkeypatch.chdir(project_root)

        with pytest.raises(SystemExit) as ex:
            cli.main(["app", "list"])

        assert ex.value.code == 1
        assert "OpenROAD backend is not implemented: local" in capsys.readouterr().err


class TestComponentList:
    """Tests for the component list CLI command."""

    def test_prints_json_by_default(
        self,
        monkeypatch: MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []

        def fake_get_component_list(
            remote: RemoteHost,
            vnode: str,
            database: str,
            app: str,
        ) -> list[ComponentInfo]:
            calls.append(("get_component_list", remote, vnode, database, app))
            return [
                ComponentInfo(
                    application_name="sample_app",
                    name="uc_order",
                    type="classsource",
                    description="Order model",
                )
            ]

        monkeypatch.setattr(cli, "get_component_list", fake_get_component_list)

        cli.main(
            [
                "component",
                "list",
                "--user",
                "test",
                "--host",
                "WINDOWS-PC",
                "--gorak-root",
                r"c:\Development\gorak",
                "--vnode",
                "vnode",
                "--database",
                "db",
                "sample_app",
            ]
        )

        remote = RemoteHost(
            user="test",
            host="WINDOWS-PC",
            gorak_root=r"c:\Development\gorak",
        )
        assert calls == [("get_component_list", remote, "vnode", "db", "sample_app")]
        assert json.loads(capsys.readouterr().out) == [
            {
                "application_name": "sample_app",
                "name": "uc_order",
                "type": "classsource",
                "description": "Order model",
            }
        ]

    def test_prints_csv_when_requested(
        self,
        monkeypatch: MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        def fake_get_component_list(
            remote: RemoteHost,
            vnode: str,
            database: str,
            app: str,
        ) -> list[ComponentInfo]:
            return [
                ComponentInfo(
                    application_name="sample_app",
                    name="uc_order",
                    type="classsource",
                    description="Order model",
                )
            ]

        monkeypatch.setattr(cli, "get_component_list", fake_get_component_list)

        cli.main(
            [
                "component",
                "list",
                "--user",
                "test",
                "--host",
                "WINDOWS-PC",
                "--gorak-root",
                r"c:\Development\gorak",
                "--vnode",
                "vnode",
                "--database",
                "db",
                "--format",
                "csv",
                "sample_app",
            ]
        )

        assert capsys.readouterr().out == (
            "application_name,name,type,description\n"
            "sample_app,uc_order,classsource,Order model\n"
        )

    def test_reads_connection_settings_from_project_env(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        project_root = tmp_path / "my_project"
        app_dir = project_root / "my_project"
        app_dir.mkdir(parents=True)
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        (project_root / ".env").write_text(
            "GORAK_BACKEND=remote\n"
            "GORAK_REMOTE_USER=project-user\n"
            "GORAK_REMOTE_HOST=project-host\n"
            "GORAK_REMOTE_ROOT=C:\\Development\\gorak\n"
            "GORAK_VNODE=project-vnode\n"
            "GORAK_DATABASE=project-db\n"
        )
        monkeypatch.chdir(app_dir)

        def fake_get_component_list(
            remote: RemoteHost,
            vnode: str,
            database: str,
            app: str,
        ) -> list[ComponentInfo]:
            calls.append(("get_component_list", remote, vnode, database, app))
            return []

        monkeypatch.setattr(cli, "get_component_list", fake_get_component_list)

        cli.main(["component", "list", "sample_app"])

        assert calls == [
            (
                "get_component_list",
                RemoteHost(
                    user="project-user",
                    host="project-host",
                    gorak_root=r"C:\Development\gorak",
                ),
                "project-vnode",
                "project-db",
                "sample_app",
            )
        ]
        assert json.loads(capsys.readouterr().out) == []

    def test_requires_remote_flags(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        for key in [
            "GORAK_REMOTE_USER",
            "GORAK_REMOTE_HOST",
            "GORAK_REMOTE_ROOT",
            "GORAK_VNODE",
            "GORAK_DATABASE",
        ]:
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(SystemExit) as ex:
            cli.main(["component", "list", "sample_app"])

        assert ex.value.code == 1
        assert "Missing OpenROAD connection settings" in capsys.readouterr().err


class TestEncodeCommand:
    """Tests for the encode CLI command."""

    def test_encodes_xml_file_to_stdout(self, capsys: CaptureFixture[str]) -> None:
        cli.main(["encode", str(FIXTURE_PATH)])

        output = capsys.readouterr().out
        assert "[framesource]" in output
        assert 'datatype = "integer"' in output
        assert "===" in output
        assert "initialize()=" in output


class TestNewCommand:
    """Tests for the new project CLI command."""

    def test_creates_project_and_prints_path(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[Path] = []
        monkeypatch.chdir(tmp_path)

        def fake_create_project(path: Path) -> GorakProject:
            calls.append(path)
            return GorakProject(
                root=tmp_path / "my_project",
                name="my_project",
            )

        monkeypatch.setattr(cli, "create_project", fake_create_project)

        cli.main(["new", "my_project"])

        assert calls == [Path("my_project")]
        assert capsys.readouterr().out == f"{tmp_path / 'my_project'}\n"

    def test_requires_project_name(self, capsys: CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as ex:
            cli.main(["new"])

        assert ex.value.code == 2
        assert "the following arguments are required: name" in capsys.readouterr().err

    def test_errors_inside_existing_project(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        monkeypatch.chdir(project_root)

        with pytest.raises(SystemExit) as ex:
            cli.main(["new", "another_project"])

        assert ex.value.code == 1
        assert "Cannot create a gorak project inside existing project" in (
            capsys.readouterr().err
        )


class TestConfigRemoteCommand:
    """Tests for the config remote CLI command."""

    def test_configures_remote_and_prints_env_path(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        project = GorakProject(root=tmp_path / "my_project", name="my_project")

        def fake_load_project(start: Path) -> GorakProject:
            calls.append(("load_project", start))
            return project

        def fake_configure_remote(
            project: GorakProject,
            host: str,
            user: str,
            gorak_root: str,
            vnode: str,
            database: str,
        ) -> Path:
            calls.append(
                ("configure_remote", project, host, user, gorak_root, vnode, database)
            )
            return project.root / ".env"

        monkeypatch.setattr(cli, "load_project", fake_load_project)
        monkeypatch.setattr(cli, "configure_remote", fake_configure_remote)

        cli.main(
            [
                "config",
                "remote",
                "--host",
                "windows-pc",
                "--user",
                "test",
                "--gorak-root",
                r"C:\Development\gorak",
                "--vnode",
                "myvnode",
                "--database",
                "exampledb",
            ]
        )

        assert calls == [
            ("load_project", Path.cwd()),
            (
                "configure_remote",
                project,
                "windows-pc",
                "test",
                r"C:\Development\gorak",
                "myvnode",
                "exampledb",
            ),
        ]
        assert capsys.readouterr().out == f"{project.root / '.env'}\n"

    def test_requires_remote_flags(self, capsys: CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as ex:
            cli.main(["config", "remote"])

        assert ex.value.code == 2
        assert "the following arguments are required" in capsys.readouterr().err

    def test_configures_remote_from_app_subdirectory(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        app_dir = project_root / "my_project"
        app_dir.mkdir(parents=True)
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        monkeypatch.chdir(app_dir)

        cli.main(
            [
                "config",
                "remote",
                "--host",
                "windows-pc",
                "--user",
                "test",
                "--gorak-root",
                r"C:\Development\gorak",
                "--vnode",
                "myvnode",
                "--database",
                "exampledb",
            ]
        )

        env_path = project_root / ".env"
        assert capsys.readouterr().out == f"{env_path}\n"
        assert dotenv_values(env_path) == {
            "GORAK_BACKEND": "remote",
            "GORAK_REMOTE_HOST": "windows-pc",
            "GORAK_REMOTE_USER": "test",
            "GORAK_REMOTE_ROOT": r"C:\Development\gorak",
            "GORAK_VNODE": "myvnode",
            "GORAK_DATABASE": "exampledb",
        }

    def test_bare_xml_file_is_not_supported(self, capsys: CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as ex:
            cli.main([str(FIXTURE_PATH)])

        assert ex.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_encodes_xml_file_to_output_path(
        self,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        output_path = tmp_path / "fm_example_frame.w4gl"

        cli.main(["encode", str(FIXTURE_PATH), "--output", str(output_path)])

        assert capsys.readouterr().out == f"{output_path}\n"
        output = output_path.read_text()
        assert "[framesource]" in output
        assert 'datatype = "integer"' in output
        assert "===" in output
        assert "initialize()=" in output


class TestRemoteInstallCommand:
    """Tests for the remote install CLI command."""

    def test_installs_remote_helpers_with_explicit_flags(
        self,
        monkeypatch: MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []

        def fake_install_packaged_remote_helpers(remote: RemoteHost) -> list[str]:
            calls.append(("install", remote))
            return ["backup-component.bat", "get-app-list.bat"]

        monkeypatch.setattr(
            cli,
            "install_packaged_remote_helpers",
            fake_install_packaged_remote_helpers,
        )

        cli.main(
            [
                "remote",
                "install",
                "--user",
                "test",
                "--host",
                "WINDOWS-PC",
                "--gorak-root",
                r"C:\Development\gorak",
            ]
        )

        assert calls == [
            (
                "install",
                RemoteHost(
                    user="test",
                    host="WINDOWS-PC",
                    gorak_root=r"C:\Development\gorak",
                ),
            )
        ]
        assert capsys.readouterr().out == (
            r"Installed 2 files to test@WINDOWS-PC:C:\Development\gorak" "\n"
        )

    def test_installs_remote_helpers_from_project_env(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        project_root = tmp_path / "my_project"
        app_dir = project_root / "my_project"
        app_dir.mkdir(parents=True)
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        (project_root / ".env").write_text(
            "GORAK_REMOTE_USER=project-user\n"
            "GORAK_REMOTE_HOST=project-host\n"
            "GORAK_REMOTE_ROOT=C:\\Development\\gorak\n"
        )
        monkeypatch.chdir(app_dir)

        def fake_install_packaged_remote_helpers(remote: RemoteHost) -> list[str]:
            calls.append(("install", remote))
            return ["backup-component.bat"]

        monkeypatch.setattr(
            cli,
            "install_packaged_remote_helpers",
            fake_install_packaged_remote_helpers,
        )

        cli.main(["remote", "install"])

        assert calls == [
            (
                "install",
                RemoteHost(
                    user="project-user",
                    host="project-host",
                    gorak_root=r"C:\Development\gorak",
                ),
            )
        ]
        assert capsys.readouterr().out == (
            r"Installed 1 file to project-user@project-host:C:\Development\gorak" "\n"
        )

    def test_requires_remote_settings_outside_project(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        for key in [
            "GORAK_REMOTE_USER",
            "GORAK_REMOTE_HOST",
            "GORAK_REMOTE_ROOT",
        ]:
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(SystemExit) as ex:
            cli.main(["remote", "install"])

        assert ex.value.code == 1
        assert "Missing remote settings" in capsys.readouterr().err

    def test_remote_scripts_are_packaged_resources(self) -> None:
        assert [resource.name for resource in cli.remote_script_resources()] == [
            "README.md",
            "applist.sql",
            "backup-component.bat",
            "get-app-list.bat",
            "get-component-list.bat",
        ]

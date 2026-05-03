import json
from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak import export as export_module
from gorak.domain import Application, ComponentInfo
from gorak.remote import RemoteHost

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "fm_example_frame.xml"


class TestAppExport:
    """Tests for the app export CLI command."""

    def test_exports_all_components_to_project_cache_and_source(
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
            "GORAK_BACKEND=local\n"
            "GORAK_VNODE=project-vnode\n"
            "GORAK_DATABASE=project-db\n"
        )
        monkeypatch.chdir(project_root)

        def fake_local_get_app_list(
            vnode: str,
            database: str,
        ) -> list[Application]:
            calls.append(("app", vnode, database))
            return [
                Application(
                    name="sample_app",
                    start_component="fm_start",
                    description="Example application",
                )
            ]

        def fake_local_get_component_list(
            vnode: str,
            database: str,
            app: str,
        ) -> list[ComponentInfo]:
            calls.append(("list", vnode, database, app))
            return [
                ComponentInfo(
                    application_name="sample_app",
                    name="first_component",
                    type="framesource",
                    description="",
                ),
                ComponentInfo(
                    application_name="sample_app",
                    name="second_component",
                    type="framesource",
                    description="",
                ),
            ]

        def fake_local_backup_component(
            vnode: str,
            database: str,
            app: str,
            component: str,
            output_path: Path,
        ) -> str:
            calls.append(("backup", vnode, database, app, component, output_path))
            output_path.write_text(FIXTURE_PATH.read_text())
            return str(output_path)

        monkeypatch.setattr(
            export_module,
            "local_get_app_list",
            fake_local_get_app_list,
        )
        monkeypatch.setattr(
            export_module,
            "local_get_component_list",
            fake_local_get_component_list,
        )
        monkeypatch.setattr(
            export_module,
            "local_backup_component",
            fake_local_backup_component,
        )

        cli.main(["app", "export", "sample_app"])

        first_xml = project_root / ".openroad" / "sample_app" / "first_component.xml"
        first_w4gl = project_root / "sample_app" / "first_component.w4gl"
        second_xml = project_root / ".openroad" / "sample_app" / "second_component.xml"
        second_w4gl = project_root / "sample_app" / "second_component.w4gl"
        assert calls == [
            ("app", "project-vnode", "project-db"),
            ("list", "project-vnode", "project-db", "sample_app"),
            (
                "backup",
                "project-vnode",
                "project-db",
                "sample_app",
                "first_component",
                first_xml,
            ),
            (
                "backup",
                "project-vnode",
                "project-db",
                "sample_app",
                "second_component",
                second_xml,
            ),
        ]
        assert json.loads((project_root / "sample_app" / "app.json").read_text()) == {
            "starting_component": "fm_start",
            "description": "Example application",
            "included_applications": [],
        }
        assert "[framesource]" in first_w4gl.read_text()
        assert "[framesource]" in second_w4gl.read_text()
        assert capsys.readouterr().out == (
            "Exporting application sample_app from local\n"
            "Retrieving application metadata\n"
            "Retrieving component list\n"
            "Exporting component sample_app::first_component\n"
            "Exporting component sample_app::second_component\n"
            "Export complete\n"
        )

    def test_exports_application_to_output_folder_outside_project(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        output_dir = tmp_path / "backup"
        monkeypatch.chdir(tmp_path)

        def fake_local_get_app_list(
            vnode: str,
            database: str,
        ) -> list[Application]:
            calls.append(("app", vnode, database))
            return [
                Application(
                    name="sample_app",
                    start_component="fm_start",
                    description="Example application",
                )
            ]

        def fake_local_get_component_list(
            vnode: str,
            database: str,
            app: str,
        ) -> list[ComponentInfo]:
            calls.append(("list", vnode, database, app))
            return [
                ComponentInfo(
                    application_name="sample_app",
                    name="first_component",
                    type="framesource",
                    description="",
                )
            ]

        def fake_local_backup_component(
            vnode: str,
            database: str,
            app: str,
            component: str,
            output_path: Path,
        ) -> str:
            calls.append(("backup", vnode, database, app, component, output_path))
            output_path.write_text(FIXTURE_PATH.read_text())
            return str(output_path)

        monkeypatch.setattr(
            export_module,
            "local_get_app_list",
            fake_local_get_app_list,
        )
        monkeypatch.setattr(
            export_module,
            "local_get_component_list",
            fake_local_get_component_list,
        )
        monkeypatch.setattr(
            export_module,
            "local_backup_component",
            fake_local_backup_component,
        )

        cli.main(
            [
                "app",
                "export",
                "--vnode",
                "vnode",
                "--database",
                "db",
                "--output",
                str(output_dir),
                "sample_app",
            ]
        )

        xml_path = output_dir / ".openroad" / "sample_app" / "first_component.xml"
        w4gl_path = output_dir / "sample_app" / "first_component.w4gl"
        assert calls == [
            ("app", "vnode", "db"),
            ("list", "vnode", "db", "sample_app"),
            ("backup", "vnode", "db", "sample_app", "first_component", xml_path),
        ]
        assert json.loads((output_dir / "sample_app" / "app.json").read_text()) == {
            "starting_component": "fm_start",
            "description": "Example application",
            "included_applications": [],
        }
        assert xml_path.read_text() == FIXTURE_PATH.read_text()
        assert "[framesource]" in w4gl_path.read_text()
        assert capsys.readouterr().out == (
            "Exporting application sample_app from local\n"
            "Retrieving application metadata\n"
            "Retrieving component list\n"
            "Exporting component sample_app::first_component\n"
            "Export complete\n"
        )

    def test_requires_output_folder_outside_project(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as ex:
            cli.main(
                [
                    "app",
                    "export",
                    "--vnode",
                    "vnode",
                    "--database",
                    "db",
                    "sample_app",
                ]
            )

        assert ex.value.code == 1
        assert "--output is required outside a gorak project" in capsys.readouterr().err

    def test_handles_empty_application_export(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        (project_root / ".env").write_text(
            "GORAK_BACKEND=local\n"
            "GORAK_VNODE=project-vnode\n"
            "GORAK_DATABASE=project-db\n"
        )
        monkeypatch.chdir(project_root)
        monkeypatch.setattr(
            export_module,
            "local_get_app_list",
            lambda vnode, database: [
                Application(
                    name="sample_app",
                    start_component="",
                    description="",
                )
            ],
        )
        monkeypatch.setattr(
            export_module, "local_get_component_list", lambda vnode, database, app: []
        )

        cli.main(["app", "export", "sample_app"])

        assert capsys.readouterr().out == (
            "Exporting application sample_app from local\n"
            "Retrieving application metadata\n"
            "Retrieving component list\n"
            "Export complete\n"
        )

    def test_exports_application_with_remote_backend(
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
            calls.append(("app", remote, vnode, database))
            return [
                Application(
                    name="sample_app",
                    start_component="fm_start",
                    description="Example application",
                )
            ]

        def fake_get_component_list(
            remote: RemoteHost,
            vnode: str,
            database: str,
            app: str,
        ) -> list[ComponentInfo]:
            calls.append(("list", remote, vnode, database, app))
            return [
                ComponentInfo(
                    application_name="sample_app",
                    name="first_component",
                    type="framesource",
                    description="",
                )
            ]

        def fake_backup_component(
            remote: RemoteHost,
            vnode: str,
            database: str,
            app: str,
            component: str,
        ) -> str:
            calls.append(("backup", remote, vnode, database, app, component))
            return r"C:\Development\gorak\repos\vnode\db\sample_app\first_component.xml"

        def fake_download_file(
            remote: RemoteHost,
            remote_path: str,
            local_path: str,
        ) -> str:
            calls.append(("download", remote, remote_path, local_path))
            Path(local_path).write_text(FIXTURE_PATH.read_text())
            return local_path

        monkeypatch.setattr(export_module, "get_app_list", fake_get_app_list)
        monkeypatch.setattr(
            export_module, "get_component_list", fake_get_component_list
        )
        monkeypatch.setattr(export_module, "backup_component", fake_backup_component)
        monkeypatch.setattr(export_module, "download_file", fake_download_file)

        cli.main(["app", "export", "sample_app"])

        remote = RemoteHost(
            user="project-user",
            host="project-host",
            gorak_root=r"C:\Development\gorak",
        )
        xml_path = project_root / ".openroad" / "sample_app" / "first_component.xml"
        w4gl_path = project_root / "sample_app" / "first_component.w4gl"
        assert calls == [
            ("app", remote, "project-vnode", "project-db"),
            ("list", remote, "project-vnode", "project-db", "sample_app"),
            (
                "backup",
                remote,
                "project-vnode",
                "project-db",
                "sample_app",
                "first_component",
            ),
            (
                "download",
                remote,
                r"C:\Development\gorak\repos\vnode\db\sample_app\first_component.xml",
                str(xml_path),
            ),
        ]
        assert json.loads((project_root / "sample_app" / "app.json").read_text()) == {
            "starting_component": "fm_start",
            "description": "Example application",
            "included_applications": [],
        }
        assert "[framesource]" in w4gl_path.read_text()
        assert capsys.readouterr().out == (
            "Exporting application sample_app from remote host project-user@project-host\n"
            "Retrieving application metadata\n"
            "Retrieving component list\n"
            "Exporting component sample_app::first_component\n"
            "Export complete\n"
        )


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

        monkeypatch.setattr(export_module, "get_app_list", fake_get_app_list)

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

        monkeypatch.setattr(export_module, "get_app_list", fake_get_app_list)

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

    def test_defaults_to_local_backend_and_requires_database_settings(
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

    def test_defaults_to_local_backend(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        monkeypatch.chdir(tmp_path)
        for key in [
            "GORAK_BACKEND",
            "GORAK_REMOTE_USER",
            "GORAK_REMOTE_HOST",
            "GORAK_REMOTE_ROOT",
        ]:
            monkeypatch.delenv(key, raising=False)

        def fake_local_get_app_list(
            vnode: str,
            database: str,
        ) -> list[Application]:
            calls.append(("local_get_app_list", vnode, database))
            return []

        monkeypatch.setattr(
            export_module, "local_get_app_list", fake_local_get_app_list
        )

        cli.main(
            [
                "app",
                "list",
                "--vnode",
                "vnode",
                "--database",
                "db",
            ]
        )

        assert calls == [("local_get_app_list", "vnode", "db")]
        assert json.loads(capsys.readouterr().out) == []

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

        monkeypatch.setattr(export_module, "get_app_list", fake_get_app_list)

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

    def test_explicit_local_backend_ignores_remote_env(
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
            "GORAK_BACKEND=local\n"
            "GORAK_REMOTE_USER=project-user\n"
            "GORAK_REMOTE_HOST=project-host\n"
            "GORAK_REMOTE_ROOT=C:\\Development\\gorak\n"
            "GORAK_VNODE=project-vnode\n"
            "GORAK_DATABASE=project-db\n"
        )
        monkeypatch.chdir(project_root)

        def fake_local_get_app_list(
            vnode: str,
            database: str,
        ) -> list[Application]:
            calls.append(("local_get_app_list", vnode, database))
            return []

        monkeypatch.setattr(
            export_module, "local_get_app_list", fake_local_get_app_list
        )

        cli.main(["app", "list"])

        assert calls == [("local_get_app_list", "project-vnode", "project-db")]
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

        monkeypatch.setattr(export_module, "get_app_list", fake_get_app_list)

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
        (project_root / ".env").write_text("GORAK_BACKEND=unsupported\n")
        monkeypatch.chdir(project_root)

        with pytest.raises(SystemExit) as ex:
            cli.main(["app", "list"])

        assert ex.value.code == 1
        assert "OpenROAD backend is not implemented: unsupported" in (
            capsys.readouterr().err
        )

    def test_uses_local_backend_from_project_env(
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
            "GORAK_BACKEND=local\n"
            "GORAK_VNODE=project-vnode\n"
            "GORAK_DATABASE=project-db\n"
        )
        monkeypatch.chdir(project_root)

        def fake_local_get_app_list(
            vnode: str,
            database: str,
        ) -> list[Application]:
            calls.append(("local_get_app_list", vnode, database))
            return [
                Application(
                    name="sample_app",
                    start_component="fm_start",
                    description="Example application",
                )
            ]

        monkeypatch.setattr(
            export_module, "local_get_app_list", fake_local_get_app_list
        )

        cli.main(["app", "list"])

        assert calls == [("local_get_app_list", "project-vnode", "project-db")]
        assert json.loads(capsys.readouterr().out) == [
            {
                "name": "sample_app",
                "start_component": "fm_start",
                "description": "Example application",
            }
        ]

import json
from pathlib import Path
from typing import cast

import pytest
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak import export as export_module
from gorak.database import OdbcSettings
from gorak.domain import Application
from gorak.remote import RemoteHost

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "fm_example_frame.xml"
FULL_APP_FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "gorak_examples.xml"


def write_project(root: Path, env: str) -> None:
    root.mkdir()
    (root / "gorak.json").write_text('{"name": "my_project"}\n')
    (root / ".env").write_text(env)


def write_local_project(root: Path) -> None:
    write_project(
        root,
        "GORAK_BACKEND=local\n"
        "GORAK_VNODE=project-vnode\n"
        "GORAK_DATABASE=project-db\n",
    )


def write_remote_project(root: Path) -> None:
    write_project(
        root,
        "GORAK_BACKEND=remote\n"
        "GORAK_REMOTE_USER=project-user\n"
        "GORAK_REMOTE_HOST=project-host\n"
        "GORAK_REMOTE_ROOT=C:\\Development\\gorak\n"
        "GORAK_VNODE=project-vnode\n"
        "GORAK_DATABASE=project-db\n",
    )


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
        write_local_project(project_root)
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

        def fake_local_backup_application(
            vnode: str,
            database: str,
            app: str,
            output_path: Path,
        ) -> str:
            calls.append(("backup", vnode, database, app, output_path))
            output_path.write_text(FULL_APP_FIXTURE_PATH.read_text())
            return str(output_path)

        monkeypatch.setattr(
            export_module,
            "local_get_app_list",
            fake_local_get_app_list,
        )
        monkeypatch.setattr(
            export_module,
            "local_backup_application",
            fake_local_backup_application,
        )

        cli.main(["app", "export", "sample_app"])

        xml_path = project_root / ".openroad" / "sample_app" / "sample_app.xml"
        assert calls == [
            ("app", "project-vnode", "project-db"),
            ("backup", "project-vnode", "project-db", "sample_app", xml_path),
        ]
        assert json.loads((project_root / "sample_app" / "app.json").read_text()) == {
            "starting_component": "fm_start",
            "description": "Example application",
            "included_applications": [
                "gorak_included",
                {"name": "finance", "image": "finance.pkg"},
            ],
        }
        assert xml_path.read_text() == FULL_APP_FIXTURE_PATH.read_text()
        assert "[framesource]" in (
            project_root / "sample_app" / "fm_example_frame.w4gl"
        ).read_text()
        assert "[proc4glsource]" in (
            project_root / "sample_app" / "p4_example_procedure.w4gl"
        ).read_text()
        assert "[classsource]" in (
            project_root / "sample_app" / "uc_example_userclass.w4gl"
        ).read_text()
        assert capsys.readouterr().out == (
            "Exporting application sample_app from local\n"
            "Retrieving application metadata\n"
            "Exporting full application XML\n"
            "Encoding component sample_app::fm_example_frame\n"
            "Encoding component sample_app::p4_example_procedure\n"
            "Encoding component sample_app::uc_example_userclass\n"
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

        def fake_local_backup_application(
            vnode: str,
            database: str,
            app: str,
            output_path: Path,
        ) -> str:
            calls.append(("backup", vnode, database, app, output_path))
            output_path.write_text(FULL_APP_FIXTURE_PATH.read_text())
            return str(output_path)

        monkeypatch.setattr(
            export_module,
            "local_get_app_list",
            fake_local_get_app_list,
        )
        monkeypatch.setattr(
            export_module,
            "local_backup_application",
            fake_local_backup_application,
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

        xml_path = output_dir / ".openroad" / "sample_app" / "sample_app.xml"
        w4gl_path = output_dir / "sample_app" / "fm_example_frame.w4gl"
        assert calls == [
            ("app", "vnode", "db"),
            ("backup", "vnode", "db", "sample_app", xml_path),
        ]
        assert json.loads((output_dir / "sample_app" / "app.json").read_text()) == {
            "starting_component": "fm_start",
            "description": "Example application",
            "included_applications": [
                "gorak_included",
                {"name": "finance", "image": "finance.pkg"},
            ],
        }
        assert xml_path.read_text() == FULL_APP_FIXTURE_PATH.read_text()
        assert "[framesource]" in w4gl_path.read_text()
        assert capsys.readouterr().out == (
            "Exporting application sample_app from local\n"
            "Retrieving application metadata\n"
            "Exporting full application XML\n"
            "Encoding component sample_app::fm_example_frame\n"
            "Encoding component sample_app::p4_example_procedure\n"
            "Encoding component sample_app::uc_example_userclass\n"
            "Export complete\n"
        )

    def test_exports_application_using_canonical_name_from_metadata(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        project_root = tmp_path / "my_project"
        write_local_project(project_root)
        monkeypatch.chdir(project_root)

        def fake_local_get_app_list(
            vnode: str,
            database: str,
        ) -> list[Application]:
            calls.append(("app", vnode, database))
            return [
                Application(
                    name="orders_mixedCase",
                    start_component="fm_start",
                    description="Example application",
                )
            ]

        def fake_local_backup_application(
            vnode: str,
            database: str,
            app: str,
            output_path: Path,
        ) -> str:
            calls.append(("backup", vnode, database, app, output_path))
            output_path.write_text(FULL_APP_FIXTURE_PATH.read_text())
            return str(output_path)

        monkeypatch.setattr(
            export_module,
            "local_get_app_list",
            fake_local_get_app_list,
        )
        monkeypatch.setattr(
            export_module,
            "local_backup_application",
            fake_local_backup_application,
        )

        cli.main(["app", "export", "orders_mixedcase"])

        xml_path = project_root / ".openroad" / "orders_mixedCase" / "orders_mixedCase.xml"
        assert calls == [
            ("app", "project-vnode", "project-db"),
            ("backup", "project-vnode", "project-db", "orders_mixedCase", xml_path),
        ]
        assert (
            project_root / "orders_mixedCase" / "fm_example_frame.w4gl"
        ).is_file()
        assert capsys.readouterr().out == (
            "Exporting application orders_mixedcase from local\n"
            "Retrieving application metadata\n"
            "Exporting full application XML\n"
            "Encoding component orders_mixedCase::fm_example_frame\n"
            "Encoding component orders_mixedCase::p4_example_procedure\n"
            "Encoding component orders_mixedCase::uc_example_userclass\n"
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
        write_local_project(project_root)
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

        def fake_local_backup_application(
            vnode: str,
            database: str,
            app: str,
            output_path: Path,
        ) -> str:
            output_path.write_text(
                '<?xml version="1.0"?><OPENROAD><APPLICATION name="sample_app" /></OPENROAD>'
            )
            return str(output_path)

        monkeypatch.setattr(
            export_module,
            "local_backup_application",
            fake_local_backup_application,
        )

        cli.main(["app", "export", "sample_app"])

        assert capsys.readouterr().out == (
            "Exporting application sample_app from local\n"
            "Retrieving application metadata\n"
            "Exporting full application XML\n"
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
        write_remote_project(project_root)
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

        def fake_backup_application(
            remote: RemoteHost,
            vnode: str,
            database: str,
            app: str,
        ) -> str:
            calls.append(("backup", remote, vnode, database, app))
            return r"C:\Development\gorak\repos\vnode\db\sample_app\sample_app.xml"

        def fake_download_file(
            remote: RemoteHost,
            remote_path: str,
            local_path: str,
        ) -> str:
            calls.append(("download", remote, remote_path, local_path))
            Path(local_path).write_text(FULL_APP_FIXTURE_PATH.read_text())
            return local_path

        monkeypatch.setattr(export_module, "get_app_list", fake_get_app_list)
        monkeypatch.setattr(export_module, "backup_application", fake_backup_application)
        monkeypatch.setattr(export_module, "download_file", fake_download_file)

        cli.main(["app", "export", "sample_app"])

        remote = RemoteHost(
            user="project-user",
            host="project-host",
            gorak_root=r"C:\Development\gorak",
        )
        xml_path = project_root / ".openroad" / "sample_app" / "sample_app.xml"
        w4gl_path = project_root / "sample_app" / "fm_example_frame.w4gl"
        assert calls == [
            ("app", remote, "project-vnode", "project-db"),
            ("backup", remote, "project-vnode", "project-db", "sample_app"),
            (
                "download",
                remote,
                r"C:\Development\gorak\repos\vnode\db\sample_app\sample_app.xml",
                str(xml_path),
            ),
        ]
        assert json.loads((project_root / "sample_app" / "app.json").read_text()) == {
            "starting_component": "fm_start",
            "description": "Example application",
            "included_applications": [
                "gorak_included",
                {"name": "finance", "image": "finance.pkg"},
            ],
        }
        assert "[framesource]" in w4gl_path.read_text()
        assert capsys.readouterr().out == (
            "Exporting application sample_app from remote host project-user@project-host\n"
            "Retrieving application metadata\n"
            "Exporting full application XML\n"
            "Encoding component sample_app::fm_example_frame\n"
            "Encoding component sample_app::p4_example_procedure\n"
            "Encoding component sample_app::uc_example_userclass\n"
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


class TestIncludesList:
    """Tests for the includes list CLI command."""

    def test_prints_included_applications(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        project_root = tmp_path / "my_project"
        write_local_project(project_root)
        monkeypatch.chdir(project_root)

        def fake_read_includes(
            connection: object,
            app: str,
        ) -> list[object]:
            calls.append((connection, app))
            return [
                "source_include",
                {"name": "image_include", "image": "image_include.pkg"},
            ]

        monkeypatch.setattr(cli, "read_includes", fake_read_includes)

        cli.main(["includes", "list", "sample_app"])

        _, app = cast(tuple[object, str], calls[0])
        assert app == "sample_app"
        assert json.loads(capsys.readouterr().out) == [
            "source_include",
            {"name": "image_include", "image": "image_include.pkg"},
        ]

    def test_can_read_application_list_through_odbc_sql_backend(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        monkeypatch.chdir(tmp_path)

        def fake_odbc_get_app_list(
            settings: OdbcSettings,
        ) -> list[Application]:
            calls.append(settings)
            return [
                Application(
                    name="sample_app",
                    start_component="fm_start",
                    description="Example application",
                )
            ]

        monkeypatch.setattr(export_module, "odbc_get_app_list", fake_odbc_get_app_list)

        cli.main(
            [
                "app",
                "list",
                "--vnode",
                "vnode",
                "--database",
                "db",
                "--sql-backend",
                "odbc",
                "--db-driver",
                "Ingres AC",
                "--db-host",
                "db-host.example",
                "--db-listen-address",
                "II7",
                "--db-database",
                "source_db",
                "--db-user",
                "ingres",
                "--db-password",
                "secret",
            ]
        )

        assert calls == [
            OdbcSettings(
                driver="Ingres AC",
                host="db-host.example",
                listen_address="II7",
                database="source_db",
                user="ingres",
                password="secret",
            )
        ]
        assert json.loads(capsys.readouterr().out) == [
            {
                "name": "sample_app",
                "start_component": "fm_start",
                "description": "Example application",
            }
        ]

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

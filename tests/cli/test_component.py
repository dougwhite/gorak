import json
from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak import export as export_module
from gorak.database import OdbcSettings
from gorak.domain import ComponentInfo
from gorak.remote import RemoteHost

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "fm_example_frame.xml"


def write_project(root: Path, env: str) -> None:
    root.mkdir(exist_ok=True)
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


@pytest.fixture(autouse=True)
def skip_sync_metadata_recording(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        export_module,
        "record_component_sync_metadata",
        lambda connection, root, app: None,
    )


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
        write_remote_project(project_root)
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

        monkeypatch.setattr(export_module, "backup_component", fake_backup_component)
        monkeypatch.setattr(export_module, "download_file", fake_download_file)

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
        w4gl_path = project_root / "app" / "fm_example_frame.w4gl"
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
        assert capsys.readouterr().out == (
            "Exporting component app::component from remote host "
            "project-user@project-host\n"
            "Wrote app/fm_example_frame.w4gl\n"
            "Wrote app/fm_example_frame.wml\n"
            "Export complete\n"
        )

    def test_overwrites_existing_project_files(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        xml_path = project_root / ".openroad" / "app" / "component.xml"
        w4gl_path = project_root / "app" / "fm_example_frame.w4gl"
        xml_path.parent.mkdir(parents=True)
        w4gl_path.parent.mkdir(parents=True)
        xml_path.write_text("old xml")
        w4gl_path.write_text("old w4gl")
        write_remote_project(project_root)
        monkeypatch.chdir(project_root)
        monkeypatch.setattr(
            export_module,
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

        monkeypatch.setattr(export_module, "download_file", fake_download_file)

        cli.main(["component", "export", "app", "component"])

        assert xml_path.read_text() == FIXTURE_PATH.read_text()
        assert w4gl_path.read_text() != "old w4gl"
        assert "[framesource]" in w4gl_path.read_text()
        assert capsys.readouterr().out == (
            "Exporting component app::component from remote host "
            "project-user@project-host\n"
            "Wrote app/fm_example_frame.w4gl\n"
            "Wrote app/fm_example_frame.wml\n"
            "Export complete\n"
        )

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
        canonical_output_path = tmp_path / "fm_example_frame.w4gl"

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

        monkeypatch.setattr(export_module, "backup_component", fake_backup_component)
        monkeypatch.setattr(export_module, "download_file", fake_download_file)

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
        assert not output_path.exists()
        assert canonical_output_path.is_file()
        assert "[framesource]" in canonical_output_path.read_text()
        assert capsys.readouterr().out == (
            "Exporting component app::component from remote host test@WINDOWS-PC\n"
            f"Wrote {canonical_output_path}\n"
            f"Wrote {canonical_output_path.with_suffix('.wml')}\n"
            "Export complete\n"
        )

    def test_rejects_output_inside_project(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        write_remote_project(project_root)
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

    def test_exports_component_with_local_backend(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        project_root = tmp_path / "my_project"
        write_local_project(project_root)
        monkeypatch.chdir(project_root)

        def fake_local_backup_component(
            vnode: str,
            database: str,
            app: str,
            component: str,
            output_path: Path,
        ) -> str:
            calls.append(("local_backup", vnode, database, app, component, output_path))
            output_path.write_text(FIXTURE_PATH.read_text())
            return str(output_path)

        monkeypatch.setattr(
            export_module,
            "local_backup_component",
            fake_local_backup_component,
        )

        cli.main(["component", "export", "app", "component"])

        xml_path = project_root / ".openroad" / "app" / "component.xml"
        w4gl_path = project_root / "app" / "fm_example_frame.w4gl"
        assert calls == [
            (
                "local_backup",
                "project-vnode",
                "project-db",
                "app",
                "component",
                xml_path,
            )
        ]
        assert xml_path.read_text() == FIXTURE_PATH.read_text()
        assert "[framesource]" in w4gl_path.read_text()
        assert capsys.readouterr().out == (
            "Exporting component app::component from local\n"
            "Wrote app/fm_example_frame.w4gl\n"
            "Wrote app/fm_example_frame.wml\n"
            "Export complete\n"
        )


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

        monkeypatch.setattr(
            export_module, "get_component_list", fake_get_component_list
        )

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

        monkeypatch.setattr(
            export_module, "get_component_list", fake_get_component_list
        )

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

        monkeypatch.setattr(
            export_module, "get_component_list", fake_get_component_list
        )

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

        def fake_local_get_component_list(
            vnode: str,
            database: str,
            app: str,
        ) -> list[ComponentInfo]:
            calls.append(("local_get_component_list", vnode, database, app))
            return [
                ComponentInfo(
                    application_name="sample_app",
                    name="p4_start",
                    type="proc4glsource",
                    description="Startup procedure",
                )
            ]

        monkeypatch.setattr(
            export_module,
            "local_get_component_list",
            fake_local_get_component_list,
        )

        cli.main(["component", "list", "sample_app"])

        assert calls == [
            ("local_get_component_list", "project-vnode", "project-db", "sample_app")
        ]
        assert json.loads(capsys.readouterr().out) == [
            {
                "application_name": "sample_app",
                "name": "p4_start",
                "type": "proc4glsource",
                "description": "Startup procedure",
            }
        ]

    def test_can_read_component_list_through_odbc_sql_backend(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        monkeypatch.chdir(tmp_path)

        def fake_odbc_get_component_list(
            settings: OdbcSettings,
            app: str,
        ) -> list[ComponentInfo]:
            calls.append((settings, app))
            return [
                ComponentInfo(
                    application_name="sample_app",
                    name="p4_start",
                    type="proc4glsource",
                    description="Startup procedure",
                )
            ]

        monkeypatch.setattr(
            export_module,
            "odbc_get_component_list",
            fake_odbc_get_component_list,
        )

        cli.main(
            [
                "component",
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
                "--db-user",
                "ingres",
                "--db-password",
                "secret",
                "sample_app",
            ]
        )

        assert calls == [
            (
                OdbcSettings(
                    driver="Ingres AC",
                    host="db-host.example",
                    listen_address="II7",
                    database="db",
                    user="ingres",
                    password="secret",
                ),
                "sample_app",
            )
        ]
        assert json.loads(capsys.readouterr().out) == [
            {
                "application_name": "sample_app",
                "name": "p4_start",
                "type": "proc4glsource",
                "description": "Startup procedure",
            }
        ]

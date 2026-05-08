from pathlib import Path

import pytest
from dotenv import dotenv_values
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak.project import GorakProject

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "fm_example_frame.xml"


class TestConfigCommand:
    """Tests for the generalized config CLI command."""

    def test_configures_local_backend_without_remote_settings(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        monkeypatch.chdir(project_root)

        cli.main(
            [
                "config",
                "--backend",
                "local",
                "--vnode",
                "myvnode",
                "--database",
                "exampledb",
            ]
        )

        env_path = project_root / ".env"
        assert capsys.readouterr().out == f"{env_path}\n"
        assert dotenv_values(env_path) == {
            "GORAK_BACKEND": "local",
            "GORAK_VNODE": "myvnode",
            "GORAK_DATABASE": "exampledb",
        }

    def test_configures_remote_backend_with_remote_settings(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        monkeypatch.chdir(project_root)

        cli.main(
            [
                "config",
                "--backend",
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

    def test_local_config_removes_stale_remote_settings(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        (project_root / ".env").write_text(
            "GORAK_BACKEND=remote\n"
            "GORAK_REMOTE_HOST=windows-pc\n"
            "GORAK_REMOTE_USER=test\n"
            "GORAK_REMOTE_ROOT=C:\\Development\\gorak\n"
            "GORAK_VNODE=oldvnode\n"
            "GORAK_DATABASE=olddb\n"
        )
        monkeypatch.chdir(project_root)

        cli.main(
            [
                "config",
                "--backend",
                "local",
                "--vnode",
                "myvnode",
                "--database",
                "exampledb",
            ]
        )

        assert dotenv_values(project_root / ".env") == {
            "GORAK_BACKEND": "local",
            "GORAK_VNODE": "myvnode",
            "GORAK_DATABASE": "exampledb",
        }

    def test_configures_odbc_sql_backend(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        monkeypatch.chdir(project_root)

        cli.main(
            [
                "config",
                "--backend",
                "local",
                "--sql-backend",
                "odbc",
                "--vnode",
                "myvnode",
                "--database",
                "exampledb",
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
            ]
        )

        assert dotenv_values(project_root / ".env") == {
            "GORAK_BACKEND": "local",
            "GORAK_SQL_BACKEND": "odbc",
            "GORAK_VNODE": "myvnode",
            "GORAK_DATABASE": "exampledb",
            "GORAK_DB_DRIVER": "Ingres AC",
            "GORAK_DB_HOST": "db-host.example",
            "GORAK_DB_LISTEN_ADDRESS": "II7",
            "GORAK_DB_USER": "ingres",
            "GORAK_DB_PASSWORD": "secret",
        }

    def test_remote_backend_requires_remote_settings(
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
            cli.main(
                [
                    "config",
                    "--backend",
                    "remote",
                    "--vnode",
                    "myvnode",
                    "--database",
                    "exampledb",
                ]
            )

        assert ex.value.code == 1
        assert "--host/GORAK_REMOTE_HOST" in capsys.readouterr().err

    def test_odbc_sql_backend_requires_odbc_settings(
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
            cli.main(
                [
                    "config",
                    "--backend",
                    "local",
                    "--sql-backend",
                    "odbc",
                    "--vnode",
                    "myvnode",
                    "--database",
                    "exampledb",
                ]
            )

        assert ex.value.code == 1
        assert "--db-driver/GORAK_DB_DRIVER" in capsys.readouterr().err


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

        def fake_configure_project(
            project: GorakProject,
            backend: str,
            vnode: str,
            database: str,
            host: str | None = None,
            user: str | None = None,
            gorak_root: str | None = None,
            sql_backend: str | None = None,
            db_driver: str | None = None,
            db_host: str | None = None,
            db_listen_address: str | None = None,
            db_database: str | None = None,
            db_user: str | None = None,
            db_password: str | None = None,
        ) -> Path:
            calls.append(
                (
                    "configure_project",
                    project,
                    backend,
                    vnode,
                    database,
                    host,
                    user,
                    gorak_root,
                    sql_backend,
                    db_driver,
                    db_host,
                    db_listen_address,
                    db_database,
                    db_user,
                    db_password,
                )
            )
            return project.root / ".env"

        monkeypatch.setattr(cli, "load_project", fake_load_project)
        monkeypatch.setattr(cli, "configure_project", fake_configure_project)

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
                "configure_project",
                project,
                "remote",
                "myvnode",
                "exampledb",
                "windows-pc",
                "test",
                r"C:\Development\gorak",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
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

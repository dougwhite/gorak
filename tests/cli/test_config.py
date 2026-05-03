from pathlib import Path

import pytest
from dotenv import dotenv_values
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak.project import GorakProject

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "fm_example_frame.xml"


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

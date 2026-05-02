from pathlib import Path

import pytest
from dotenv import dotenv_values
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak.project import GorakProject
from gorak.remote import RemoteHost

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "fm_example_frame.xml"


class TestRemoteExportComponent:
    """Tests for the remote export-component CLI command."""

    def test_exports_and_downloads_component(
        self,
        monkeypatch: MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []

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
            return local_path

        monkeypatch.setattr(cli, "backup_component", fake_backup_component)
        monkeypatch.setattr(cli, "download_file", fake_download_file)

        cli.main(
            [
                "remote",
                "export-component",
                "--ssh-target",
                "test@WINDOWS-PC",
                "--gorak-root",
                r"c:\Development\gorak",
                "--vnode",
                "vnode",
                "--database",
                "db",
                "--app",
                "app",
                "--component",
                "component",
                "--output",
                "component.xml",
            ]
        )

        remote = RemoteHost(
            ssh_target="test@WINDOWS-PC",
            gorak_root=r"c:\Development\gorak",
        )
        assert calls == [
            ("backup", remote, "vnode", "db", "app", "component"),
            (
                "download",
                remote,
                r"C:\Development\gorak\repos\vnode\db\app\component.xml",
                "component.xml",
            ),
        ]
        assert capsys.readouterr().out == "component.xml\n"

    def test_requires_output(self, capsys: CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as ex:
            cli.main(
                [
                    "remote",
                    "export-component",
                    "--ssh-target",
                    "test@WINDOWS-PC",
                    "--gorak-root",
                    r"c:\Development\gorak",
                    "--vnode",
                    "vnode",
                    "--database",
                    "db",
                    "--app",
                    "app",
                    "--component",
                    "component",
                ]
            )

        assert ex.value.code == 2
        assert (
            "the following arguments are required: --output" in capsys.readouterr().err
        )


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

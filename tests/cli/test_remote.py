from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak.remote import RemoteHost

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "fm_example_frame.xml"


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

    def test_checks_remote_helpers_with_explicit_flags(
        self,
        monkeypatch: MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []

        def fake_verify_remote_helpers(remote: RemoteHost) -> None:
            calls.append(("check", remote))

        monkeypatch.setattr(cli, "verify_remote_helpers", fake_verify_remote_helpers)

        cli.main(
            [
                "remote",
                "check",
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
                "check",
                RemoteHost(
                    user="test",
                    host="WINDOWS-PC",
                    gorak_root=r"C:\Development\gorak",
                ),
            )
        ]
        assert capsys.readouterr().out == (
            r"Remote helpers OK on test@WINDOWS-PC:C:\Development\gorak" "\n"
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
            "backup-application.bat",
            "backup-component.bat",
            "get-app-list.bat",
            "get-component-list.bat",
            "get-component-sync-metadata.bat",
            "get-include-list.bat",
            "gorak-helpers.json",
        ]

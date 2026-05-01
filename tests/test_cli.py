from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
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

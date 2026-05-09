import json
import shutil
from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "gorak_examples.xml"


class TestDebugAudit:
    """Tests for the debug audit CLI command."""

    def test_audits_xml_file_as_json(self, capsys: CaptureFixture[str]) -> None:
        cli.main(["debug", "audit", str(FIXTURE_PATH)])

        output = json.loads(capsys.readouterr().out)
        assert output["path"] == str(FIXTURE_PATH)
        assert output["application"]["name"] == "gorak_examples"
        assert [component["name"] for component in output["components"]] == [
            "fm_complex_frame",
            "fm_example_frame",
            "p4_example_procedure",
            "uc_example_userclass",
        ]

    def test_audits_xml_file_with_missing_only(
        self,
        capsys: CaptureFixture[str],
    ) -> None:
        cli.main(["debug", "audit", "--missing-only", str(FIXTURE_PATH)])

        output = json.loads(capsys.readouterr().out)
        assert output["application"] is None
        assert [component["name"] for component in output["components"]] == [
            "fm_complex_frame"
        ]
        assert output["components"][0]["missing_paths"] == [
            "COMPONENT[fm_complex_frame]/mainbarbottom",
            "COMPONENT[fm_complex_frame]/mainbartop",
        ]

    def test_audits_all_cached_xml_in_project(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        project = tmp_path / "my_project"
        cache = project / ".openroad" / "sample_app"
        cache.mkdir(parents=True)
        (project / "gorak.json").write_text('{"name": "my_project"}\n')
        shutil.copy(FIXTURE_PATH, cache / "sample_app.xml")
        monkeypatch.chdir(project)

        cli.main(["debug", "audit", "--all"])

        output = json.loads(capsys.readouterr().out)
        assert [result["path"] for result in output] == [
            ".openroad/sample_app/sample_app.xml"
        ]
        assert output[0]["application"]["name"] == "gorak_examples"

    def test_audits_all_cached_xml_with_missing_only(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        project = tmp_path / "my_project"
        cache = project / ".openroad" / "sample_app"
        cache.mkdir(parents=True)
        (project / "gorak.json").write_text('{"name": "my_project"}\n')
        shutil.copy(FIXTURE_PATH, cache / "sample_app.xml")
        monkeypatch.chdir(project)

        cli.main(["debug", "audit", "--all", "--missing-only"])

        output = json.loads(capsys.readouterr().out)
        assert [result["path"] for result in output] == [
            ".openroad/sample_app/sample_app.xml"
        ]
        assert output[0]["application"] is None
        assert [component["name"] for component in output[0]["components"]] == [
            "fm_complex_frame"
        ]

    def test_audit_all_requires_project(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
        capsys: CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as ex:
            cli.main(["debug", "audit", "--all"])

        assert ex.value.code == 1
        assert "No gorak project found" in capsys.readouterr().err

    def test_audit_requires_path_or_all(
        self,
        capsys: CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as ex:
            cli.main(["debug", "audit"])

        assert ex.value.code == 1
        assert "Missing XML_FILE or --all" in capsys.readouterr().err

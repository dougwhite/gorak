import json
from pathlib import Path

from pytest import CaptureFixture

from gorak import cli

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "gorak_examples.xml"


class TestDebugAudit:
    """Tests for the debug audit CLI command."""

    def test_audits_xml_file_as_json(self, capsys: CaptureFixture[str]) -> None:
        cli.main(["debug", "audit", str(FIXTURE_PATH)])

        output = json.loads(capsys.readouterr().out)
        assert output["application"]["name"] == "gorak_examples"
        assert [component["name"] for component in output["components"]] == [
            "fm_complex_frame",
            "fm_example_frame",
            "p4_example_procedure",
            "uc_example_userclass",
        ]

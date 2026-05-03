from pathlib import Path

import pytest
from pytest import CaptureFixture

from gorak import cli

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "fm_example_frame.xml"


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

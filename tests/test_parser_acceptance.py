from pathlib import Path
from lxml import etree
from openroad_vscode_sync.parser import parse_xml, Component

# Simple example frame export from OpenROAD for verification purposes
EXAMPLE_FRAMESOURCE_PATH = Path(__file__).parent / "fixtures" / "fm_example_frame.xml"

class TestParseXmlAcceptance:
    """Acceptance tests to check that `parse_xml()` correctly handles 
       our example OpenROAD xml exports."""

    def test_handles_framesource_export(self) -> None:
        """Ensures `parse_xml()` can correctly parse our framesource example"""
        
        # Import the xml
        xml = etree.parse(EXAMPLE_FRAMESOURCE_PATH)
        component = parse_xml(xml)

        # Check the finalk component name/type matches what we think it should
        assert component.name == 'fm_example_frame'
        assert component.type == 'framesource'

        # Check our props look good
        assert component.props["datatype"] == "integer"
        assert component.props["templatename"] == "standard"

        # Check we correctly ignored the problematic probs
        assert "topform" not in component.props

        # Check the script worked correctly
        assert "initialize()=" in component.script
        assert "CurFrame.Trace(text = " in component.script

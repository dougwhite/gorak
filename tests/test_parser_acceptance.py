from pathlib import Path

from lxml import etree

from gorak.parser import encode_w4gl, parse_xml

# Simple example frame export from OpenROAD for verification purposes
EXAMPLE_FRAMESOURCE_PATH = Path(__file__).parent / "fixtures" / "fm_example_frame.xml"
EXAMPLE_USERCLASS_PATH = Path(__file__).parent / "fixtures" / "uc_example_userclass.xml"
EXAMPLE_USERCLASS_W4GL_PATH = (
    Path(__file__).parent / "fixtures" / "uc_example_userclass.w4gl"
)


class TestParseXmlAcceptance:
    """Acceptance tests to check that `parse_xml()` correctly handles
    our example OpenROAD xml exports."""

    def test_handles_framesource_export(self) -> None:
        """Ensures `parse_xml()` can correctly parse our framesource example"""

        # Import the xml
        xml = etree.parse(EXAMPLE_FRAMESOURCE_PATH)
        component = parse_xml(xml)

        # Check the finalk component name/type matches what we think it should
        assert component.name == "fm_example_frame"
        assert component.type == "framesource"

        # Check our props look good
        assert component.props["datatype"] == "integer"
        assert component.props["templatename"] == "standard"

        # Check we correctly ignored the problematic probs
        assert "topform" not in component.props

        # Check the script worked correctly
        assert component.script is not None
        assert "initialize()=" in component.script
        assert "CurFrame.Trace(text = " in component.script

    def test_handles_userclass_export(self) -> None:
        xml = etree.parse(EXAMPLE_USERCLASS_PATH)
        component = parse_xml(xml)

        assert component.name == "uc_example_userclass"
        assert component.type == "classsource"
        assert component.props["superclass"] == "userobject"
        assert component.props["attributes"] == {
            "id": "INTEGER NOT NULL",
            "name": "VARCHAR(32) NOT NULL",
            "nullable_prop": "VARCHAR(32)",
            "date_prop": "DATE NOT NULL",
            "float_prop": "FLOAT NOT NULL",
            "money_prop": "MONEY NOT NULL",
            "decimal_prop": "DECIMAL(10,0) NOT NULL",
        }
        assert component.props["methods"] == {
            "ExampleMethod": "METHOD RETURNING INTEGER NOT NULL",
            "PrivateMethod": "PRIVATE METHOD",
            "ObjectReturnMethod": "METHOD RETURNING STRINGOBJECT",
        }
        assert component.script is not None
        assert "METHOD ExampleMethod() =" in component.script
        assert "METHOD ObjectReturnMethod() =" in component.script
        assert "METHOD PrivateMethod() =" in component.script

    def test_encodes_userclass_export_to_w4gl_fixture(self) -> None:
        xml = etree.parse(EXAMPLE_USERCLASS_PATH)
        component = parse_xml(xml)

        assert encode_w4gl(component) == EXAMPLE_USERCLASS_W4GL_PATH.read_text()

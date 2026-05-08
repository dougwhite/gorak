from pathlib import Path

from lxml import etree

from gorak.parser import (
    encode_w4gl,
    parse_application_xml,
    parse_components_xml,
    parse_xml,
)

EXAMPLE_FRAMESOURCE_PATH = Path(__file__).parent / "fixtures" / "fm_example_frame.xml"
EXAMPLE_USERCLASS_PATH = Path(__file__).parent / "fixtures" / "uc_example_userclass.xml"
EXAMPLE_USERCLASS_W4GL_PATH = (
    Path(__file__).parent / "fixtures" / "uc_example_userclass.w4gl"
)
GORAK_EXAMPLES_PATH = Path(__file__).parent / "fixtures" / "gorak_examples.xml"


class TestParseXmlAcceptance:
    """Fixture-level checks against real-ish OpenROAD XML exports."""

    def test_handles_framesource_export(self) -> None:
        xml = etree.parse(EXAMPLE_FRAMESOURCE_PATH)
        component = parse_xml(xml)

        assert component.name == "fm_example_frame"
        assert component.type == "framesource"
        assert component.props["datatype"] == "integer"
        assert component.props["templatename"] == "standard"
        assert component.props["fielddefaults"]["field_types"]["barfield"]["type"] == (
            "matrixfield"
        )
        assert "topform" not in component.props
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

    def test_parses_all_components_from_full_application_export(self) -> None:
        xml = etree.parse(GORAK_EXAMPLES_PATH)
        components = parse_components_xml(xml)

        assert [component.name for component in components] == [
            "fm_example_frame",
            "p4_example_procedure",
            "uc_example_userclass",
        ]
        assert [component.type for component in components] == [
            "framesource",
            "proc4glsource",
            "classsource",
        ]

    def test_parses_application_metadata_from_full_application_export(self) -> None:
        xml = etree.parse(GORAK_EXAMPLES_PATH)
        export = parse_application_xml(xml)

        assert export.application.name == "gorak_examples"
        assert export.application.start_component == ""
        assert export.application.description == ""
        assert export.included_applications == [
            "gorak_included",
            {"name": "finance", "image": "finance.pkg"},
        ]
        assert [component.name for component in export.components] == [
            "fm_example_frame",
            "p4_example_procedure",
            "uc_example_userclass",
        ]

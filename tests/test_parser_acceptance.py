from pathlib import Path
from tempfile import TemporaryDirectory

from lxml import etree

from gorak.domain import Component
from gorak.export import apply_field_default_inheritance
from gorak.parser import (
    encode_w4gl,
    encode_wml,
    parse_application_xml,
    parse_components_xml,
    parse_xml,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
EXAMPLE_FRAMESOURCE_PATH = Path(__file__).parent / "fixtures" / "fm_example_frame.xml"
EXAMPLE_FRAMESOURCE_W4GL_PATH = (
    Path(__file__).parent / "fixtures" / "fm_example_frame.w4gl"
)
EXAMPLE_FRAMESOURCE_WML_PATH = (
    Path(__file__).parent / "fixtures" / "fm_example_frame.wml"
)
COMPLEX_FRAMESOURCE_PATH = Path(__file__).parent / "fixtures" / "fm_complex_frame.xml"
COMPLEX_FRAMESOURCE_W4GL_PATH = (
    Path(__file__).parent / "fixtures" / "fm_complex_frame.w4gl"
)
COMPLEX_FRAMESOURCE_WML_PATH = (
    Path(__file__).parent / "fixtures" / "fm_complex_frame.wml"
)
EXAMPLE_USERCLASS_PATH = Path(__file__).parent / "fixtures" / "uc_example_userclass.xml"
EXAMPLE_USERCLASS_W4GL_PATH = (
    Path(__file__).parent / "fixtures" / "uc_example_userclass.w4gl"
)
EXAMPLE_PROCEDURE_W4GL_PATH = (
    Path(__file__).parent / "fixtures" / "p4_example_procedure.w4gl"
)
GORAK_EXAMPLES_PATH = Path(__file__).parent / "fixtures" / "gorak_examples.xml"


def encode_w4gl_with_project_defaults(component_name: str) -> str:
    component = parse_xml(etree.parse(FIXTURE_ROOT / f"{component_name}.xml"))
    apply_fixture_defaults([component])
    return encode_w4gl(component)


def full_app_components_with_project_defaults() -> dict[str, Component]:
    export = parse_application_xml(etree.parse(GORAK_EXAMPLES_PATH))
    apply_fixture_defaults(export.components)
    return {component.name: component for component in export.components}


def apply_fixture_defaults(components: list[Component]) -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "field_defaults.json").write_text(
            (FIXTURE_ROOT / "example.skel" / "field_defaults.json").read_text()
        )
        apply_field_default_inheritance(
            root=root,
            app="example_application",
            components=components,
        )


class TestParseXmlAcceptance:
    """Fixture-level checks against real-ish OpenROAD XML exports."""

    def test_handles_framesource_export(self) -> None:
        xml = etree.parse(EXAMPLE_FRAMESOURCE_PATH)
        component = parse_xml(xml)

        assert component.name == "fm_example_frame"
        assert component.type == "framesource"
        assert component.props["datatype"] == "integer"
        assert component.props["templatename"] == "standard"
        assert component.props["fielddefaults"]["field_styles"][0]["type"] == "barfield"
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

    def test_encodes_framesource_export_to_w4gl_fixture(self) -> None:
        assert encode_w4gl_with_project_defaults("fm_example_frame") == (
            EXAMPLE_FRAMESOURCE_W4GL_PATH.read_text()
        )

    def test_encodes_framesource_export_to_wml_fixture(self) -> None:
        xml = etree.parse(EXAMPLE_FRAMESOURCE_PATH)
        component = parse_xml(xml)

        assert encode_wml(component) == EXAMPLE_FRAMESOURCE_WML_PATH.read_text().strip()

    def test_handles_complex_framesource_export(self) -> None:
        xml = etree.parse(COMPLEX_FRAMESOURCE_PATH)
        component = parse_xml(xml)

        assert component.name == "fm_complex_frame"
        assert component.type == "framesource"
        assert component.props["datatype"] == "uc_example_userclass"
        assert component.props["templatename"] == "standard"
        assert component.markup is not None
        assert "<tabfolder" in component.markup
        assert "<tabpagearray" in component.markup

    def test_encodes_complex_framesource_export_to_w4gl_fixture(self) -> None:
        assert encode_w4gl_with_project_defaults("fm_complex_frame") == (
            COMPLEX_FRAMESOURCE_W4GL_PATH.read_text()
        )

    def test_encodes_complex_framesource_export_to_wml_fixture(self) -> None:
        xml = etree.parse(COMPLEX_FRAMESOURCE_PATH)
        component = parse_xml(xml)

        assert encode_wml(component) == COMPLEX_FRAMESOURCE_WML_PATH.read_text().strip()

    def test_parses_all_components_from_full_application_export(self) -> None:
        xml = etree.parse(GORAK_EXAMPLES_PATH)
        components = parse_components_xml(xml)

        assert [component.name for component in components] == [
            "fm_complex_frame",
            "fm_example_frame",
            "p4_example_procedure",
            "uc_example_userclass",
        ]
        assert [component.type for component in components] == [
            "framesource",
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
            "fm_complex_frame",
            "fm_example_frame",
            "p4_example_procedure",
            "uc_example_userclass",
        ]

    def test_encodes_full_application_components_to_golden_fixtures(self) -> None:
        components = full_app_components_with_project_defaults()

        assert encode_w4gl(components["fm_complex_frame"]) == (
            COMPLEX_FRAMESOURCE_W4GL_PATH.read_text()
        )
        assert encode_wml(components["fm_complex_frame"]) == (
            COMPLEX_FRAMESOURCE_WML_PATH.read_text().strip()
        )
        assert encode_w4gl(components["fm_example_frame"]) == (
            EXAMPLE_FRAMESOURCE_W4GL_PATH.read_text()
        )
        assert encode_wml(components["fm_example_frame"]) == (
            EXAMPLE_FRAMESOURCE_WML_PATH.read_text().strip()
        )
        assert encode_w4gl(components["p4_example_procedure"]) == (
            EXAMPLE_PROCEDURE_W4GL_PATH.read_text()
        )
        assert encode_w4gl(components["uc_example_userclass"]) == (
            EXAMPLE_USERCLASS_W4GL_PATH.read_text()
        )

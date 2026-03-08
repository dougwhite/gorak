import pytest
import tomlkit
from pathlib import Path
from lxml import etree
from textwrap import dedent
from openroad_vscode_sync.parser import (
    parse_xml, extract_props, write_script, write_props, get_base_path, Component
)

# Simple example frame export from OpenROAD for verification purposes
EXAMPLE_XML_PATH = Path(__file__).parent / "fixtures" / "fm_example_frame.xml"

@pytest.fixture
def example_xml() -> Path:
    """Provides the example xml file as a preloaded fixture"""
    return etree.parse(EXAMPLE_XML_PATH)

class TestParseXml:
    """Tests for the `parse_xml()` function"""

    def test_parse_xml_returns_a_component_class(self, example_xml: Path) -> None:
        component = parse_xml(example_xml)
        assert isinstance(component, Component)
    
    def test_component_has_a_matching_script(self, example_xml: Path) -> None:
        component = parse_xml(example_xml)

        assert component.script is not None
        assert "initialize()=" in component.script
        assert "CurFrame.Trace" in component.script
    
    def test_component_has_correct_properties(self, example_xml: Path) -> None:
        component = parse_xml(example_xml)
        assert component.props["datatype"] == "integer"
        assert component.props["windowheight"] == "1625"
    
    def test_component_has_a_name_and_type(self, example_xml: Path) -> None:
        component = parse_xml(example_xml)
        assert component.name == "fm_example_frame"
        assert component.type == "framesource"

class TestExtractProps:
    """Tests for the `extract_props()` function"""

    def test_extract_props_returns_a_dict(self, example_xml: Path) -> None:
        component_node = example_xml.find(".//COMPONENT")
        props = extract_props(component_node)

        assert isinstance(props, dict)
    
    def test_extract_props_retrieves_component_properties(self, example_xml: Path) -> None:
        component_node = example_xml.find(".//COMPONENT")
        props = extract_props(component_node)

        assert props["datatype"] == "integer"
        assert props["templatename"] == "standard"
        assert props["windowheight"] == "1625"
        assert props["windowwidth"] == "2292"
    
    def test_extract_props_skips_ignored_props(self, example_xml: Path) -> None:
        component_node = example_xml.find(".//COMPONENT")
        props = extract_props(component_node)

        assert "script" not in props
        assert "startmenu" not in props
        assert "topform" not in props
        assert "fielddefaults" not in props

class TestWriteScript:
    """Tests for the `write_script()` function"""

    def test_write_script_saves_a_script_to_a_dot_4gl_file(self, tmp_path: Path) -> None:
        # Create a fake component with script
        fake_script = dedent("""
            initialize() =
            {
                CurFrame.Trace(text = 'Hello');
            }
        """).strip()

        component = Component(name="fake", type="framesource", script=fake_script, props={})

        # Call the write_script function
        output_path = tmp_path / "test_frame.4gl"
        write_script(component, output_path)

        # Verify
        assert output_path.exists()
        assert output_path.read_text().strip() == fake_script

class TestWriteProps:
    """Tests for the `write_props()` function"""

    def test_write_props_saves_the_props_to_a_dot_toml_file(self, tmp_path: Path) -> None:
        # Setup a fake component with simple props
        fake_props = {
            "name": "fm_example_frame",
            "type": "framesource",
            "datatype": "integer",
            "templatename": "standard",
            "hasstatusbar": "1",
        }
        component = Component(name="fake", type="framesource", script="", props=fake_props)

        # Call the write_props function
        output_path = tmp_path / "test_frame.props.toml"
        write_props(component, output_path)

        # Verify the file exists and matches the correct props
        assert output_path.exists()
        
        parsed_back = tomlkit.parse(output_path.read_text())
        assert parsed_back == fake_props

class TestGetBasePath:
    """Tests for the `get_base_path()` function"""

    def test_base_path_returns_correct_path(self, tmp_path: Path) -> None:
        # Set up a fake repo folder
        project_root = tmp_path / "MyRepo"
        project_root.mkdir()

        # Call get_base_path to generate the component path
        base_path = get_base_path("myapp", "fm_example_frame", project_root)

        expected = project_root / "myapp" / "fm_example_frame"
        assert base_path == expected
        assert base_path.is_absolute()
        assert isinstance(base_path, Path)
    
    def test_base_path_accepts_string_root_path(self, tmp_path: Path) -> None:
        # Set up a fake repo folder
        project_root = tmp_path / "MyRepo"
        project_root.mkdir()
        root_str = str(project_root)

        # Call get_base_path to generate the component path
        base_path = get_base_path("myapp", "fm_example_frame", root_str)
        expected = project_root / "myapp" / "fm_example_frame"
        assert base_path == expected
        assert isinstance(base_path, Path)

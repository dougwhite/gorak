import pytest
import tomlkit
from pathlib import Path
from lxml import etree
from textwrap import dedent
from openroad_vscode_sync.parser import load_component, extract_props, write_script, write_props, Component

@pytest.fixture
def example_xml_path() -> Path:
    """Path to our example frame fixture"""
    return Path(__file__).parent / "fixtures" / "fm_example_frame.xml"

class TestLoadComponent:
    """Tests for the `load_component()` function"""

    def test_load_component_returns_a_component_class(self, example_xml_path: Path) -> None:
        component = load_component(example_xml_path)
        assert isinstance(component, Component)
    
    def test_component_has_a_matching_script(self, example_xml_path: Path) -> None:
        component = load_component(example_xml_path)

        assert component.script is not None
        assert "initialize()=" in component.script
        assert "CurFrame.Trace" in component.script
    
    def test_component_has_correct_properties(self, example_xml_path: Path) -> None:
        component = load_component(example_xml_path)

        assert component.props["name"] == "fm_example_frame"
        assert component.props["type"] == "framesource"
        assert component.props["datatype"] == "integer"

class TestExtractProps:
    """Tests for the `extract_props()` function"""

    def test_extract_props_returns_a_dict(self, example_xml_path: Path) -> None:
        tree = etree.parse(str(example_xml_path))
        component_node = tree.find(".//COMPONENT")
        props = extract_props(component_node)

        assert isinstance(props, dict)
    
    def test_extract_props_retrieves_meta_values(self, example_xml_path: Path) -> None:
        tree = etree.parse(str(example_xml_path))
        component_node = tree.find(".//COMPONENT")
        props = extract_props(component_node)

        assert props["name"] == "fm_example_frame"
        assert props["type"] == "framesource"
    
    def test_extract_props_retrieves_component_properties(self, example_xml_path: Path) -> None:
        tree = etree.parse(str(example_xml_path))
        component_node = tree.find(".//COMPONENT")
        props = extract_props(component_node)

        assert props["datatype"] == "integer"
        assert props["templatename"] == "standard"
        assert props["windowheight"] == "1625"
        assert props["windowwidth"] == "2292"
    
    def test_extract_props_skips_ignored_props(self, example_xml_path: Path) -> None:
        tree = etree.parse(str(example_xml_path))
        component_node = tree.find(".//COMPONENT")
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

        component = Component(script=fake_script, props={})

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
        component = Component(script="", props=fake_props)

        # Call the write_props function
        output_path = tmp_path / "test_frame.props.toml"
        write_props(component, output_path)

        # Verify the file exists and matches the correct props
        assert output_path.exists()
        
        parsed_back = tomlkit.parse(output_path.read_text())
        assert parsed_back == fake_props
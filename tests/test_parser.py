from pathlib import Path
import pytest
from openroad_vscode_sync.parser import load_component, Component

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

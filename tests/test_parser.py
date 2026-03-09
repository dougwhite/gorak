from pathlib import Path
from textwrap import dedent

import pytest
import tomlkit
from lxml import etree
from tomlkit.items import Table

from openroad_vscode_sync.parser import (
    Component,
    extract_props,
    get_base_path,
    parse_xml,
    toml_props,
    write_script,
)
from tests._helpers import _wrap_xml


class TestParseXml:
    """Tests for the `parse_xml()` function"""

    def test_parse_xml_returns_a_component_class(self) -> None:
        xml = _wrap_xml('<COMPONENT name="fm_component_check" xsi:type="framesource"></COMPONENT>')
        component = parse_xml(xml)

        assert isinstance(component, Component)
    
    def test_component_has_a_matching_script(self) -> None:
        xml = _wrap_xml("""
            <COMPONENT name="fm_has_script" xsi:type="framesource">
                <script><![CDATA[initialize()= { CurFrame.Trace(text = 'Hello'); }]]></script>
            </COMPONENT>
        """)
        component = parse_xml(xml)

        assert component.script is not None
        assert "initialize()=" in component.script
        assert "CurFrame.Trace(text = 'Hello')" in component.script
    
    def test_component_has_correct_properties(self) -> None:
        xml = _wrap_xml("""
            <COMPONENT name="fm_example_frame" xsi:type="framesource">
                <datatype>integer</datatype>
                <windowheight>1625</windowheight>
            </COMPONENT>
        """)
        component = parse_xml(xml)

        assert component.props["datatype"] == "integer"
        assert component.props["windowheight"] == "1625"
    
    def test_component_has_a_name_and_type(self) -> None:
        xml = _wrap_xml("""
            <COMPONENT name="fm_example_frame" xsi:type="framesource">
            </COMPONENT>
        """)
        component = parse_xml(xml)
        
        assert component.name == "fm_example_frame"
        assert component.type == "framesource"
    
    def test_missing_component_node_raises_an_exception(self) -> None:
        bad_xml = _wrap_xml('')
        
        with pytest.raises(ValueError) as ex:
            parse_xml(bad_xml)
        
        assert "Missing <COMPONENT> node" in str(ex.value)

    def test_missing_script_doesnt_raise_an_exception(self) -> None:
        no_script = _wrap_xml('<COMPONENT name="fm_example_frame" xsi:type="framesource"></COMPONENT>')
        component = parse_xml(no_script)

        assert component.script is None
    
    def test_missing_name_raises_an_exception(self) -> None:
        no_name = _wrap_xml('<COMPONENT xsi:type="framesource"></COMPONENT>')

        with pytest.raises(ValueError) as ex:
            parse_xml(no_name)
        
        assert "<COMPONENT> node must have a name attribute" in str(ex.value)
    
    def test_missing_type_raises_an_exception(self) -> None:
        no_type = _wrap_xml('<COMPONENT name="fm_example_frame"></COMPONENT>')

        with pytest.raises(ValueError) as ex:
            parse_xml(no_type)
        
        assert "<COMPONENT> node must have an xsi:type attribute" in str(ex.value)


class TestExtractProps:
    """Tests for the `extract_props()` function"""

    def test_extract_props_returns_a_dict(self) -> None:
        node = etree.fromstring("<COMPONENT></COMPONENT>")
        props = extract_props(node)

        assert isinstance(props, dict)
    
    def test_extract_props_retrieves_component_properties(self) -> None:
        node = etree.fromstring("<COMPONENT><datatype>integer</datatype></COMPONENT>")
        props = extract_props(node)

        assert props["datatype"] == "integer"
    
    def test_default_ignore_list_is_respected(self) -> None:
        node = etree.fromstring("<COMPONENT><script>ignore me</script></COMPONENT>")
        props = extract_props(node)

        assert "script" not in props
    
    def test_the_ignore_list_can_be_overridden(self) -> None:
        node = etree.fromstring("<COMPONENT><datatype>ignored</datatype><script>not ignored</script></COMPONENT>")
        props = extract_props(node, {"datatype"})

        assert "datatype" not in props
        assert "script" in props

class TestTomlProps:
    """Tests for the `toml_props()` function"""

    def test_returns_a_toml_document(self) -> None:
        component = Component("fm_simple", "framesource", {})
        doc = toml_props(component)

        assert isinstance(doc, tomlkit.TOMLDocument)
    
    def test_uses_component_type_as_section_header(self) -> None:
        component = Component("fm_simple", "framesource", {})
        doc = toml_props(component)

        assert "framesource" in doc
        assert isinstance(doc["framesource"], Table)
    
    def test_props_are_encoded_correctly_under_section(self) -> None:
        component = Component("fm_simple", "framesource", {"foo": "bar"})
        doc = toml_props(component)
        
        section = doc["framesource"]
        assert isinstance(section, Table)
        assert section["foo"] == tomlkit.string("bar")

    def test_nested_props_encode_correctly(self) -> None:
        component = Component("fm_nested", "framesource", {
            "flat": "value",
            "nested" : { "foo": "bar" }
        })
        doc = toml_props(component)

        # Test the main section heading contains both flat and nested children
        main_section = doc["framesource"]
        assert isinstance(main_section, Table)
        assert "flat" in main_section
        assert "nested" in main_section
        assert main_section["flat"] == tomlkit.string("value")

        # Test the nested section contains a flat value
        subsection = main_section["nested"]
        assert isinstance(subsection, Table)
        assert "foo" in subsection
        assert subsection["foo"] == tomlkit.string("bar")

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

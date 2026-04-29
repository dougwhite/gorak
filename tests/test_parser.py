from textwrap import dedent

import pytest
import tomlkit
from lxml import etree
from tomlkit.items import Table

from gorak.parser import (
    Component,
    encode_4gl,
    extract_props,
    join_segments,
    parse_xml,
    toml_props,
)
from tests._helpers import _wrap_xml


@pytest.fixture
def simple_frame() -> Component:
    """A simple framesource component fixture for testing"""
    return Component(
        name="fm_simple",
        type="framesource",
        props={"foo": "bar"},
        script=dedent("""
            initialize() =
            {
                CurFrame.Trace(text = 'Hello');
            }
        """).strip()
    )

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

class TestJoinSegments:
    """Tests for the `join_segments()` function"""

    def test_empty_list_returns_an_empty_string(self) -> None:
        result = join_segments([], separator="===")
        assert result == ""
    
    def test_single_segment_returns_the_segment_without_separators(self) -> None:
        result = join_segments(["single segment"], separator="===")
        assert result == "single segment"
    
    def test_multiple_segments_are_joined_with_separators_and_blank_lines(self) -> None:
        segments = ["first segment", "second segment", "third segment"]
        result = join_segments(segments, separator="===")

        expected = dedent("""
            first segment
            
            ===
            
            second segment
            
            ===
            
            third segment
        """).strip()
        
        assert result == expected
    
    def test_none_segments_are_removed_from_the_list(self) -> None:
        segments = ["first segment", None, "third segment"]
        result = join_segments(segments, separator="===")

        expected = dedent("""
            first segment
            
            ===
            
            third segment
        """).strip()
        
        assert result == expected
     
    def test_all_whitespace_segments_are_treated_as_empty_but_included(self) -> None:
        segments = ["first segment", "", "third segment"]
        result = join_segments(segments, separator="===")

        expected = dedent("""
            first segment
            
            ===
            

            
            ===
            
            third segment
        """).strip()
        
        assert result == expected
    
    def test_a_single_segment_and_a_none_returns_without_separators(self) -> None:
        segments = ["only segment", None]
        result = join_segments(segments, separator="===")

        expected = "only segment"
        assert result == expected

    def test_none_and_a_single_segment_returns_without_separators(self) -> None:
        segments = [None, "only segment"]
        result = join_segments(segments, separator="===")

        expected = "only segment"
        assert result == expected

class Test4glEncode:
    """Tests for the `encode_4gl()` function"""

    def test_component_to_4gl_returns_a_string(self, simple_frame: Component) -> None:
        result = encode_4gl(simple_frame)
        assert isinstance(result, str)
    
    def test_component_encodes_correctly_to_string(self, simple_frame: Component) -> None:
        result = encode_4gl(simple_frame)
        expected = dedent("""
            [framesource]
            foo = "bar"
            
            ===
            
            initialize() =
            {
                CurFrame.Trace(text = 'Hello');
            }
        """).strip()
        
        assert result == expected
    
    def test_component_with_no_script_just_returns_promps_toml(self) -> None:
        component = Component("simple", "constsource", { "datatype": "integer", "defaultvalue": "5" })
        result = encode_4gl(component)
        
        expected = dedent("""
            [constsource]
            datatype = "integer"
            defaultvalue = "5"
        """).strip()
        
        assert result == expected

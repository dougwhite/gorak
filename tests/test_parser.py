from textwrap import dedent

import pytest
import tomlkit
from lxml import etree
from tomlkit.items import Table

from gorak.domain import Component
from gorak.parser import (
    encode_w4gl,
    encode_wml,
    extract_attributes,
    extract_methods,
    extract_props,
    join_segments,
    parse_application_xml,
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
        """).strip(),
    )


class TestParseXml:
    """Tests for the `parse_xml()` function"""

    def test_parse_xml_returns_a_component_class(self) -> None:
        xml = _wrap_xml(
            '<COMPONENT name="fm_component_check" xsi:type="framesource"></COMPONENT>'
        )
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
        bad_xml = _wrap_xml("")

        with pytest.raises(ValueError) as ex:
            parse_xml(bad_xml)

        assert "Missing <COMPONENT> node" in str(ex.value)

    def test_missing_script_doesnt_raise_an_exception(self) -> None:
        no_script = _wrap_xml(
            '<COMPONENT name="fm_example_frame" xsi:type="framesource"></COMPONENT>'
        )
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

    def test_frame_component_encodes_topform_as_wml_markup(self) -> None:
        xml = _wrap_xml("""
            <COMPONENT name="fm_example_frame" xsi:type="framesource">
                <topform>
                    <bgcolor>70</bgcolor>
                    <childfields>
                        <row xsi:type="subform">
                            <name>example_composite_field</name>
                            <childfields>
                                <row xsi:type="buttonfield">
                                    <name>example_button</name>
                                    <script><![CDATA[ON click =
{
    MESSAGE 'Hello World!';
}]]></script>
                                    <textlabel><![CDATA[Button]]></textlabel>
                                </row>
                            </childfields>
                        </row>
                    </childfields>
                </topform>
            </COMPONENT>
        """)

        component = parse_xml(xml)

        assert component.markup is not None
        markup = etree.fromstring(component.markup)
        subform = markup.find("subform")
        assert markup.tag == "topform"
        assert markup.get("bgcolor") == "70"
        assert subform is not None
        assert subform.get("name") == "example_composite_field"
        button = subform.find("buttonfield")
        assert button is not None
        assert button.get("name") == "example_button"
        assert button.get("textlabel") == "Button"
        assert button.findtext("script") is not None
        assert "MESSAGE 'Hello World!';" in button.findtext("script", "")

    def test_frame_markup_omits_attributes_that_match_field_defaults(self) -> None:
        xml = _wrap_xml("""
            <COMPONENT name="fm_example_frame" xsi:type="framesource">
                <topform>
                    <bgcolor>70</bgcolor>
                    <fgcolor>1</fgcolor>
                    <childfields>
                        <row xsi:type="buttonfield">
                            <name>example_button</name>
                            <bgcolor>70</bgcolor>
                            <fgcolor>72</fgcolor>
                            <textlabel><![CDATA[Button]]></textlabel>
                        </row>
                    </childfields>
                </topform>
                <fielddefaults>
                    <row xsi:type="matrixfield">
                        <clienttext>buttonfield</clienttext>
                        <bgcolor>70</bgcolor>
                        <fgcolor>1</fgcolor>
                        <childfields>
                            <row xsi:type="buttonfield">
                                <bgcolor>70</bgcolor>
                                <fgcolor>72</fgcolor>
                                <textlabel><![CDATA[Button]]></textlabel>
                            </row>
                        </childfields>
                    </row>
                </fielddefaults>
            </COMPONENT>
        """)

        component = parse_xml(xml)

        assert component.markup is not None
        markup = etree.fromstring(component.markup)
        button = markup.find("buttonfield")
        assert markup.get("bgcolor") is None
        assert markup.get("fgcolor") is None
        assert button is not None
        assert button.attrib == {"name": "example_button"}

    def test_frame_markup_uses_best_matching_default_for_repeated_field_types(
        self,
    ) -> None:
        xml = _wrap_xml("""
            <COMPONENT name="fm_example_frame" xsi:type="framesource">
                <topform>
                    <childfields>
                        <row xsi:type="entryfield">
                            <name>example_entryfield</name>
                            <bgcolor>84</bgcolor>
                            <lines>3</lines>
                        </row>
                    </childfields>
                </topform>
                <fielddefaults>
                    <row xsi:type="matrixfield">
                        <clienttext>entryfield</clienttext>
                        <childfields>
                            <row xsi:type="entryfield">
                                <bgcolor>84</bgcolor>
                                <lines>1</lines>
                            </row>
                        </childfields>
                    </row>
                    <row xsi:type="matrixfield">
                        <clienttext>entryfield</clienttext>
                        <childfields>
                            <row xsi:type="entryfield">
                                <bgcolor>84</bgcolor>
                                <lines>3</lines>
                            </row>
                        </childfields>
                    </row>
                </fielddefaults>
            </COMPONENT>
        """)

        component = parse_xml(xml)

        assert component.markup is not None
        markup = etree.fromstring(component.markup)
        entryfield = markup.find("entryfield")
        assert entryfield is not None
        assert entryfield.attrib == {"name": "example_entryfield"}

    def test_frame_markup_formats_dense_elements_across_multiple_lines(self) -> None:
        xml = _wrap_xml("""
            <COMPONENT name="fm_example_frame" xsi:type="framesource">
                <topform>
                    <childfields>
                        <row xsi:type="entryfield">
                            <name>example_entryfield</name>
                            <datatype>varchar(100)</datatype>
                            <xleft>104</xleft>
                            <ytop>188</ytop>
                            <width>3531</width>
                            <height>188</height>
                        </row>
                    </childfields>
                </topform>
            </COMPONENT>
        """)

        component = parse_xml(xml)

        assert component.markup is not None
        assert (
            """
  <entryfield
    name="example_entryfield"
    datatype="varchar(100)"
    xleft="104"
    ytop="188"
    width="3531"
    height="188"
  />
""".strip()
            in component.markup
        )
        etree.fromstring(component.markup)

    def test_frame_markup_preserves_nested_row_attributes(self) -> None:
        xml = _wrap_xml("""
            <COMPONENT name="fm_example_frame" xsi:type="framesource">
                <topform>
                    <childfields>
                        <row xsi:type="optionfield">
                            <name>method</name>
                            <valuelist>
                                <choiceitems row_class="choicedetail">
                                    <row enumdisplay="GET" enumtext="GET" enumvalue="1" />
                                </choiceitems>
                            </valuelist>
                        </row>
                    </childfields>
                </topform>
            </COMPONENT>
        """)

        component = parse_xml(xml)

        assert component.markup is not None
        markup = etree.fromstring(component.markup)
        choiceitems = markup.find("./optionfield/valuelist/choiceitems")
        choice = markup.find("./optionfield/valuelist/choiceitems/row")
        assert choiceitems is not None
        assert choiceitems.get("row_class") == "choicedetail"
        assert choice is not None
        assert choice.get("enumdisplay") == "GET"
        assert choice.get("enumtext") == "GET"
        assert choice.get("enumvalue") == "1"


class TestParseApplicationXml:
    """Tests for application-level metadata in full OpenROAD exports."""

    def test_parses_included_applications_in_openroad_order(self) -> None:
        xml = etree.fromstring("""
            <OPENROAD>
                <APPLICATION name="sample_app">
                    <included_apps>
                        <row>
                            <sequence>1</sequence>
                            <appname>source_include</appname>
                        </row>
                        <row>
                            <sequence>2</sequence>
                            <appname>image_include</appname>
                            <imgfilename>image_include.pkg</imgfilename>
                        </row>
                    </included_apps>
                </APPLICATION>
            </OPENROAD>
        """)

        export = parse_application_xml(xml)

        assert export.included_applications == [
            "source_include",
            {"name": "image_include", "image": "image_include.pkg"},
        ]

    def test_strips_force_included_core_plb(self) -> None:
        xml = etree.fromstring("""
            <OPENROAD>
                <APPLICATION name="sample_app">
                    <included_apps>
                        <row>
                            <appname>source_include</appname>
                        </row>
                        <row>
                            <appname>core</appname>
                            <imgfilename>core.plb</imgfilename>
                        </row>
                    </included_apps>
                </APPLICATION>
            </OPENROAD>
        """)

        export = parse_application_xml(xml)

        assert export.included_applications == ["source_include"]


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
        node = etree.fromstring(
            "<COMPONENT><datatype>ignored</datatype><script>not ignored</script></COMPONENT>"
        )
        props = extract_props(node, {"datatype"})

        assert "datatype" not in props
        assert "script" in props

    def test_complex_row_table_props_are_ignored(self) -> None:
        node = etree.fromstring("""
            <COMPONENT>
                <attributes>
                    <row>
                        <displayname>id</displayname>
                        <datatype>integer</datatype>
                    </row>
                </attributes>
                <methods>
                    <row>
                        <displayname>ExampleMethod</displayname>
                    </row>
                </methods>
            </COMPONENT>
        """)

        props = extract_props(node)

        assert "attributes" not in props
        assert "methods" not in props


class TestExtractAttributes:
    """Tests for the `extract_attributes()` function"""

    def test_extracts_attribute_declarations_by_display_name(self) -> None:
        node = etree.fromstring("""
            <attributes>
                <row>
                    <displayname>id</displayname>
                    <datatype>integer</datatype>
                </row>
                <row>
                    <displayname>name</displayname>
                    <datatype>varchar(32)</datatype>
                </row>
            </attributes>
        """)

        assert extract_attributes(node) == {
            "id": "INTEGER NOT NULL",
            "name": "VARCHAR(32) NOT NULL",
        }

    def test_nullable_attributes_omit_not_null(self) -> None:
        node = etree.fromstring("""
            <attributes>
                <row>
                    <displayname>nullable_prop</displayname>
                    <datatype>varchar(32)</datatype>
                    <isnullable>1</isnullable>
                </row>
            </attributes>
        """)

        assert extract_attributes(node) == {"nullable_prop": "VARCHAR(32)"}


class TestExtractMethods:
    """Tests for the `extract_methods()` function"""

    def test_extracts_method_declarations_by_display_name(self) -> None:
        node = etree.fromstring("""
            <methods>
                <row>
                    <displayname>ExampleMethod</displayname>
                    <datatype>integer</datatype>
                </row>
                <row>
                    <displayname>ObjectReturnMethod</displayname>
                    <datatype>stringobject</datatype>
                    <isnullable>1</isnullable>
                </row>
            </methods>
        """)

        assert extract_methods(node) == {
            "ExampleMethod": "METHOD RETURNING INTEGER NOT NULL",
            "ObjectReturnMethod": "METHOD RETURNING STRINGOBJECT",
        }

    def test_private_methods_are_marked_private(self) -> None:
        node = etree.fromstring("""
            <methods>
                <row>
                    <displayname>PrivateMethod</displayname>
                    <isprivate>1</isprivate>
                </row>
            </methods>
        """)

        assert extract_methods(node) == {"PrivateMethod": "PRIVATE METHOD"}


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
        component = Component(
            "fm_nested", "framesource", {"flat": "value", "nested": {"foo": "bar"}}
        )
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


class TestW4glEncode:
    """Tests for the `encode_w4gl()` function"""

    def test_component_to_w4gl_returns_a_string(self, simple_frame: Component) -> None:
        result = encode_w4gl(simple_frame)
        assert isinstance(result, str)

    def test_component_encodes_correctly_to_string(
        self, simple_frame: Component
    ) -> None:
        result = encode_w4gl(simple_frame)
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


class TestWmlEncode:
    """Tests for the `encode_wml()` function."""

    def test_returns_component_markup_when_present(self) -> None:
        component = Component("fm_simple", "framesource", {}, markup="<topform/>")

        assert encode_wml(component) == "<topform/>"

    def test_returns_none_for_components_without_markup(self) -> None:
        component = Component("p4_simple", "proc4glsource", {})

        assert encode_wml(component) is None

    def test_component_with_no_script_just_returns_promps_toml(self) -> None:
        component = Component(
            "simple", "constsource", {"datatype": "integer", "defaultvalue": "5"}
        )
        result = encode_w4gl(component)

        expected = dedent("""
            [constsource]
            datatype = "integer"
            defaultvalue = "5"
        """).strip()

        assert result == expected

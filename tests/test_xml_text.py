"""Synthetic control-character fixtures; no external database or customer source."""

import json
from pathlib import Path

import pytest
from lxml import etree

from gorak.contract_source import decode_component
from gorak.errors import ProjectError
from gorak.field_defaults import element_value
from gorak.importer import signature
from gorak.parser import encode_w4gl, parse_component_node, parse_w4gl
from gorak.style_values import decode_value as value_node
from gorak.wml_writer import parse_markup
from gorak.xml_shapes import order_children
from gorak.xml_text import find_text, set_text, text_value
from tests.native_source import write_component

XSI = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
PI = "<?ingres_invalidxmlchar 7?>"


def node(text: str) -> etree._Element:
    return etree.fromstring(text.encode(), etree.XMLParser(strip_cdata=False))


def project(tmp_path: Path) -> Path:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    (tmp_path / "field_defaults.json").write_text("{}")
    return folder / "sample.w4gl"


def frame() -> etree._Element:
    result = node(
        f'<COMPONENT {XSI} name="sample" xsi:type="framesource">'
        f"<script>// before {PI} after\ninitialize() = {{}}</script>"
        "<fielddefaults><row_class>formfield</row_class></fielddefaults>"
        '<topform><childfields><row xsi:type="entryfield">'
        "<name>input</name><datatype>varchar(30)</datatype>"
        f"<defaultstring>before{PI} after</defaultstring>"
        f"<script>// event {PI} tail</script>"
        "</row><row_class>formfield</row_class></childfields></topform>"
        "</COMPONENT>"
    )

    order_children(result, "framesource")
    return result


@pytest.mark.parametrize("code", [0, 2, 7, 11, 12, 16, 28, 31, 65534, 65535])
@pytest.mark.parametrize("cdata", [False, True])
def test_text_round_trip_preserves_all_segments(code: int, cdata: bool) -> None:
    value = chr(code) + " before ]]> & <\r\n" + chr(code) * 2 + " after " + chr(code)
    source = etree.Element("script")
    set_text(source, value, cdata=cdata)
    reconstructed = node(etree.tostring(source, encoding="unicode"))
    assert text_value(reconstructed) == value
    assert len(reconstructed) == 4
    # Replacement must remove old instructions and tails.
    set_text(reconstructed, "ordinary")
    assert len(reconstructed) == 0
    assert text_value(reconstructed) == "ordinary"


@pytest.mark.parametrize(
    "instruction",
    [
        "<?other 7?>",
        "<?ingres_invalidxmlchar nope?>",
        "<?ingres_invalidxmlchar -1?>",
        "<?ingres_invalidxmlchar 1114112?>",
        "<?ingres_invalidxmlchar 55296?>",
        "<?ingres_invalidxmlchar 65?>",
        "<?ingres_invalidxmlchar 999999999999999999999?>",
    ],
)
def test_unsupported_instructions_refuse_clearly(instruction: str) -> None:
    with pytest.raises(ProjectError, match="instruction|code point|XML-invalid"):
        text_value(node(f"<script>before{instruction}after</script>"))


def test_comments_do_not_eat_following_text() -> None:
    assert text_value(node(f"<script>a<!-- note -->b{PI}c</script>")) == "ab\x07c"


def test_structural_instruction_refused() -> None:
    with pytest.raises(ProjectError, match="text property"):
        parse_markup(f"<frame>{PI}<topform/></frame>")


def test_unknown_instruction_in_ignored_metadata_is_not_silently_dropped() -> None:
    with pytest.raises(ProjectError, match="Unsupported XML processing instruction"):
        parse_component_node(
            node(
                f'<COMPONENT {XSI} name="sample" xsi:type="classsource">'
                "<queries><row><?unknown 1?></row></queries></COMPONENT>"
            )
        )


def test_main_script_and_toml_round_trip(tmp_path: Path) -> None:
    source = node(
        f'<COMPONENT {XSI} name="sample" xsi:type="proc4glsource">'
        f"<versshortremarks>before{PI}after</versshortremarks>"
        "<script><?ingres_invalidxmlchar 11?>// comment "
        f"{PI} remaining comment\nreturn;<?ingres_invalidxmlchar 28?></script>"
        "</COMPONENT>"
    )
    parsed = parse_component_node(source)
    encoded = encode_w4gl(parsed)
    assert "\\u0007" in encoded.split("===")[0]
    assert parse_w4gl(encoded, "sample") == parsed
    path = project(tmp_path)
    path.write_text(encoded)
    rebuilt = decode_component(path)
    assert text_value(rebuilt.find("script")) == text_value(source.find("script"))
    assert find_text(rebuilt, "versshortremarks") == "before\x07after"
    assert (
        parse_component_node(node(etree.tostring(rebuilt, encoding="unicode")))
        == parsed
    )


def test_compact_wml_properties_and_events_round_trip(tmp_path: Path) -> None:
    source = frame()
    parsed = parse_component_node(source)
    assert parsed.markup is not None
    assert "<defaultstring>" in parsed.markup
    assert PI in parsed.markup
    path = project(tmp_path)
    write_component(path, source)
    rebuilt = decode_component(path)
    assert (
        find_text(rebuilt, "topform/childfields/row/defaultstring")
        == "before\x07 after"
    )
    assert find_text(rebuilt, "topform/childfields/row/script") == "// event \x07 tail"
    assert parse_component_node(rebuilt) == parsed


def test_defaults_json_distinguishes_literal_escape_text() -> None:
    value = element_value(
        node(f"<defaultstring>actual{PI} literal \\u0007</defaultstring>")
    )
    assert value == "actual\x07 literal \\u0007"
    decoded = value_node("defaultstring", json.loads(json.dumps(value)))
    assert text_value(decoded) == value


def test_signature_does_not_hide_instruction_tail_whitespace_or_target() -> None:
    assert signature(node(f"<script>a{PI} b</script>")) != signature(
        node(f"<script>a{PI}b</script>")
    )
    assert signature(node(f"<script>a{PI}b</script>")) != signature(
        node("<script>a<?different 7?>b</script>")
    )


def test_duplicate_wml_property_refused(tmp_path: Path) -> None:
    path = project(tmp_path)
    path.write_text("[framesource]\n")
    path.with_suffix(".wml").write_text(
        f'<frame><topform><entryfield name="input" defaultstring="first">'
        f"<defaultstring>second{PI}</defaultstring></entryfield></topform></frame>"
    )
    with pytest.raises(ProjectError, match="Duplicate"):
        decode_component(path)


def test_metadata_overlay_replaces_script_instructions_without_losing_tails(
    tmp_path: Path,
) -> None:
    from gorak.component_edits import overlay_metadata

    source = node(
        f'<COMPONENT {XSI} name="sample" xsi:type="proc4glsource">'
        f"<script>\n// before {PI} after\nreturn;\n</script></COMPONENT>"
    )
    parsed = parse_component_node(source)
    parsed.script = "// changed\x02 comment\nreturn;"
    path = project(tmp_path)
    path.write_text(encode_w4gl(parsed))
    overlay_metadata(source, path)
    assert find_text(source, "script") == "\n// changed\x02 comment\nreturn;\n"
    assert source.find("script").xpath("./processing-instruction()")[0].text == "2"


def test_declarations_and_tagged_values_preserve_characters(tmp_path: Path) -> None:
    source = node(
        f'<COMPONENT {XSI} name="sample" xsi:type="classsource">'
        f"<attributes><row><displayname>value</displayname><datatype>integer{PI}</datatype>"
        "<isnullable>1</isnullable></row><row_class>attributeobject</row_class></attributes>"
        f"<methods><row><displayname>read_value</displayname><datatype>integer{PI}</datatype>"
        "<isnullable>1</isnullable></row><row_class>methodobject</row_class></methods>"
        f"<taggedvalues><row><name>note{PI}tail</name><value>before{PI}after</value></row>"
        "<row_class>taggedvalue</row_class></taggedvalues></COMPONENT>"
    )
    parsed = parse_component_node(source)
    path = project(tmp_path)
    path.write_text(encode_w4gl(parsed))
    assert parse_component_node(decode_component(path)) == parsed


def test_scalar_element_tail_is_not_silently_lost(tmp_path: Path) -> None:
    source = frame()
    parsed = parse_component_node(source)
    path = project(tmp_path)
    write_component(path, source)
    assert parsed.markup is not None
    path.with_suffix(".wml").write_text(
        parsed.markup.replace("</defaultstring>", "</defaultstring>unexpected")
    )
    with pytest.raises(ProjectError, match="Text properties|scalar markup"):
        decode_component(path)

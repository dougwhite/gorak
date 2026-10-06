"""Preserve structured cursors and canonicalize only empty macro collections."""

from pathlib import Path

import pytest
from lxml import etree

from gorak.contract_source import equivalent
from gorak.parser import NS, parse_component_node
from gorak.portable_source import restore_component
from tests.native_source import write_component


@pytest.mark.parametrize("field_kind", ["entryfield", "buttonfield", "flexibleform"])
@pytest.mark.parametrize("cursor_kind", ["system", "bitmap"])
def test_cursor_object_roundtrip(
    tmp_path: Path, field_kind: str, cursor_kind: str
) -> None:
    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}"
        name="sample" xsi:type="framesource"><topform><childfields>
        <row xsi:type="{field_kind}"><name>field</name><cursor/></row>
        <row_class>formfield</row_class></childfields></topform><fielddefaults/>
        </COMPONENT>''')
    cursor = node.find(".//cursor")
    assert cursor is not None
    if cursor_kind == "system":
        etree.SubElement(cursor, "syscursor").text = "1"
    else:
        from gorak.bitmap_codec import encode
        from tests.test_image_assets import bitmap

        etree.SubElement(cursor, "obj_encoded").text = encode(bitmap())
    source = tmp_path / "sample.w4gl"
    write_component(source, node)
    assert "<cursor" in source.with_suffix(".wml").read_text()
    restored = restore_component(source)
    assert equivalent(node, restored)
    if cursor_kind == "system":
        assert restored.findtext(".//cursor/syscursor") == "1"
        source.with_suffix(".wml").write_text(
            source.with_suffix(".wml")
            .read_text()
            .replace('syscursor="1"', 'syscursor="2"')
        )
        assert restore_component(source).findtext(".//cursor/syscursor") == "2"


@pytest.mark.parametrize("kind", ["proc4glsource", "framesource", "frametemplate"])
@pytest.mark.parametrize("present", [False, True])
def test_empty_macro_variables_use_native_absent_form(
    tmp_path: Path, kind: str, present: bool
) -> None:
    node = etree.Element("COMPONENT", name="sample", nsmap=NS)
    node.set(f"{{{NS['xsi']}}}type", kind)
    if present:
        etree.SubElement(node, "macro_vars")
    if kind != "proc4glsource":
        etree.SubElement(node, "topform")
        etree.SubElement(node, "fielddefaults")
    source = tmp_path / "sample.w4gl"
    write_component(source, node)
    restored = restore_component(source)
    assert restored.find("macro_vars") is None
    assert "macro_vars" not in source.read_text()
    assert equivalent(node, restored)


def test_macro_definitions_preserve_order_values_and_duplicates(tmp_path: Path) -> None:
    from gorak.component_edits import overlay_metadata
    from gorak.macro_variables import read_macros
    from gorak.xml_text import set_text

    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}"
        name="sample" xsi:type="proc4glsource"><macro_vars>
        <row><name>$LABEL</name><value/><shortremark/></row>
        <row><name>$LABEL</name><value>second</value></row>
        <row_class>macrovariable</row_class></macro_vars></COMPONENT>''')
    set_text(node.find("macro_vars/row/value"), "  café\n\x07  ")
    source = tmp_path / "sample.w4gl"
    write_component(source, node)
    assert "[[proc4glsource.macro_vars]]" in source.read_text()
    restored = restore_component(source)
    assert read_macros(restored) == read_macros(node)
    assert equivalent(node, restored)
    source.write_text(
        source.read_text().replace('value = "second"', 'value = "changed"')
    )
    overlay_metadata(restored, source)
    assert read_macros(restored)[1]["value"] == "changed"
    source.write_text("[proc4glsource]\n")
    overlay_metadata(restored, source)
    assert restored.find("macro_vars") is None


@pytest.mark.parametrize("content", ["text", "<row><unknown>value</unknown></row>"])
def test_unknown_macro_structure_is_refused(content: str) -> None:
    from gorak.errors import ProjectError

    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}"
        name="sample" xsi:type="proc4glsource"><macro_vars>{content}</macro_vars>
        </COMPONENT>''')
    with pytest.raises(ProjectError, match="macro_vars"):
        parse_component_node(node)


def test_legacy_empty_spelling_cannot_erase_cached_definitions(tmp_path: Path) -> None:
    from gorak.component_edits import overlay_metadata
    from gorak.errors import ProjectError

    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}"
        name="sample" xsi:type="proc4glsource"><macro_vars>
        <row><name>$LABEL</name><value>Keep</value></row>
        <row_class>macrovariable</row_class></macro_vars></COMPONENT>''')
    source = tmp_path / "sample.w4gl"
    source.write_text('[proc4glsource]\nmacro_vars = ""\n')
    with pytest.raises(ProjectError, match="Re-export"):
        overlay_metadata(node, source)
    assert node.findtext("macro_vars/row/value") == "Keep"


def test_existing_empty_macro_spelling_is_still_readable(tmp_path: Path) -> None:
    source = tmp_path / "sample.w4gl"
    source.write_text('[proc4glsource]\nmacro_vars = ""\n')
    assert restore_component(source).find("macro_vars") is None


@pytest.mark.parametrize(
    "metadata",
    [
        'macro_vars = "unexpected"',
        'macro_vars = [{name = "$LABEL", value = 3}]',
        'macro_vars = [{name = "$LABEL", unknown = "data"}]',
    ],
)
def test_invalid_macro_source_is_refused(tmp_path: Path, metadata: str) -> None:
    from gorak.errors import ProjectError

    source = tmp_path / "sample.w4gl"
    source.write_text("[proc4glsource]\n" + metadata + "\n")
    with pytest.raises(ProjectError, match="macro_vars"):
        restore_component(source)

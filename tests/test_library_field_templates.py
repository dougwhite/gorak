"""External library declarations and reusable field trees reconstruct without caches."""

from copy import deepcopy
from pathlib import Path

import pytest
from lxml import etree

from gorak.audit import audit_component_node
from gorak.contract_source import equivalent
from gorak.errors import ProjectError
from gorak.parser import NS, parse_component_node
from gorak.portable_source import overlay_component, restore_component
from tests.native_source import write_component

XSI = f"{{{NS['xsi']}}}type"


def test_external_library_metadata_roundtrip_and_edit(tmp_path: Path) -> None:
    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}" name="library"
        xsi:type="extlibsource"><versshortremarks>Example library</versshortremarks>
        <uniqueid>{{00020430-0000-0000-C000-000000000046}}</uniqueid>
        <majorversion>2</majorversion><minorversion>0</minorversion></COMPONENT>''')
    source = tmp_path / "library.w4gl"
    write_component(source, node)
    assert "[extlibsource]" in source.read_text()
    assert not source.with_suffix(".wml").exists()
    assert equivalent(node, restore_component(source))
    source.write_text(
        source.read_text().replace('minorversion = "0"', 'minorversion = "1"')
    )
    assert restore_component(source).findtext("minorversion") == "1"
    overlay_component(node, source)
    assert node.findtext("minorversion") == "1"


@pytest.mark.parametrize("kind", ["buttonfield", "stackfield", "flexibleform"])
def test_field_template_both_roles_preserve_type_and_content(
    tmp_path: Path, kind: str
) -> None:
    node = etree.Element("COMPONENT", name="sample", nsmap=NS)
    node.set(XSI, "fieldtemplate")
    for tag in ("framefield", "reportfield"):
        field = etree.SubElement(node, tag)
        field.set(XSI, kind)
        etree.SubElement(field, "name").text = "sample"
        etree.SubElement(field, "width").text = "1200"
        etree.SubElement(field, "script").text = "  initialize() = {}\n"
        if kind != "buttonfield":
            children = etree.SubElement(field, "childfields")
            child = etree.SubElement(children, "row")
            child.set(XSI, "buttonfield")
            etree.SubElement(child, "name").text = "action"
            etree.SubElement(child, "textlabel").text = "Run"
            etree.SubElement(children, "row_class").text = "formfield"
    etree.SubElement(node, "simpletitle").text = "Example"
    etree.SubElement(node, "columntitle").text = "Column"
    etree.SubElement(node, "assistantproc").text = "configure_field"
    source = tmp_path / "sample.w4gl"
    write_component(source, node)
    wml = source.with_suffix(".wml")
    assert "<fieldtemplate>" in wml.read_text()
    assert "<framefield\n" in wml.read_text() or "<framefield " in wml.read_text()
    assert f'type="{kind}"' in wml.read_text()
    assert not source.with_suffix(".fielddefaults.json").exists()
    assert equivalent(node, restore_component(source))
    assert not audit_component_node(node)["missing_paths"]
    wml.write_text(wml.read_text().replace('width="1200"', 'width="2400"'))
    overlay_component(node, source)
    assert node.findtext("framefield/width") == "2400"
    assert node.find("reportfield").get(XSI) == kind
    # Removing one role must not delete the other.
    original = deepcopy(node)
    tree = etree.fromstring(wml.read_bytes())
    tree.remove(tree.find("reportfield"))
    wml.write_bytes(etree.tostring(tree))
    restored = restore_component(source)
    assert restored.find("reportfield") is None
    assert restored.find("framefield") is not None
    assert not equivalent(original, restored)


def test_template_images_and_nested_prototypes(tmp_path: Path) -> None:
    from gorak.bitmap_codec import encode
    from tests.test_image_assets import bitmap

    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}" name="sample" xsi:type="fieldtemplate">
        <framefield xsi:type="matrixfield"><name>grid</name><childfields>
        <row xsi:type="columnfield"><name>column</name><protofield xsi:type="entryfield">
        <datatype>varchar(10)</datatype></protofield></row><row_class>formfield</row_class>
        </childfields></framefield><reportfield xsi:type="imagefield"><name>image</name>
        <bgbitmap><obj_encoded/></bgbitmap></reportfield></COMPONENT>''')
    node.find(".//obj_encoded").text = encode(bitmap())
    source = tmp_path / "sample.w4gl"
    write_component(source, node)
    assert 'src="images/' in source.with_suffix(".wml").read_text()
    assert equivalent(node, restore_component(source))


@pytest.mark.parametrize("kind", ["extlibsource", "fieldtemplate"])
def test_unknown_native_metadata_is_refused(kind: str) -> None:
    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}" name="sample" xsi:type="{kind}">
        <extension><row><payload>unknown</payload></row></extension></COMPONENT>''')
    with pytest.raises(ProjectError, match="extension metadata"):
        parse_component_node(node)


@pytest.mark.parametrize(
    "markup",
    [
        "<frame/>",
        "<fieldtemplate><topform/></fieldtemplate>",
        "<fieldtemplate><framefield/><framefield/></fieldtemplate>",
        '<fieldtemplate><framefield type="proc4glsource"/></fieldtemplate>',
        '<fieldtemplate><framefield type="entryfield" mystery="value"/></fieldtemplate>',
    ],
)
def test_invalid_template_markup_is_refused(tmp_path: Path, markup: str) -> None:
    source = tmp_path / "sample.w4gl"
    source.write_text("[fieldtemplate]\n")
    source.with_suffix(".wml").write_text(markup)
    with pytest.raises(ProjectError):
        restore_component(source)


def test_template_requires_layout(tmp_path: Path) -> None:
    source = tmp_path / "sample.w4gl"
    source.write_text("[fieldtemplate]\n")
    with pytest.raises(ProjectError, match="requires a WML"):
        restore_component(source)


def test_template_geometry_normalization_is_narrow() -> None:
    from gorak.frame_geometry import normalized_markup

    before = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}" name="sample" xsi:type="fieldtemplate">
        <framefield xsi:type="buttonfield"><width>1200</width><height>300</height>
        <textlabel>Run</textlabel></framefield></COMPONENT>''')
    after = deepcopy(before)
    after.find("framefield/width").text = "1198"
    after.find("framefield/height").text = "302"
    markup = normalized_markup(before, after)
    assert markup is not None and markup.startswith("<fieldtemplate>")
    after.find("framefield/textlabel").text = "Changed"
    assert normalized_markup(before, after) is None
    after.find("framefield/textlabel").text = "Run"
    after.find("framefield/width").text = "1300"
    assert normalized_markup(before, after) is None


@pytest.mark.parametrize("kind", ["extlibsource", "fieldtemplate"])
def test_supported_tagged_metadata_and_unknown_properties(
    tmp_path: Path, kind: str
) -> None:
    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}" name="sample" xsi:type="{kind}">
        <taggedvalues><row><name>category</name><value>example</value></row>
        <row_class>taggedvalue</row_class></taggedvalues></COMPONENT>''')
    source = tmp_path / "sample.w4gl"
    write_component(source, node)
    assert equivalent(node, restore_component(source))
    etree.SubElement(node.find("taggedvalues/row"), "availability").text = "1"
    with pytest.raises(ProjectError, match="tagged values"):
        parse_component_node(node)

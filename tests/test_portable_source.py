from pathlib import Path

import pytest
from lxml import etree

from gorak.export import apply_field_default_inheritance
from gorak.importer import signature
from gorak.parser import encode_w4gl, encode_wml, parse_component_node
from gorak.portable_source import restore_component, write_companions
from gorak.project import ProjectError


def test_frame_reconstruction_needs_no_export_cache(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    xml = Path("tests/fixtures/fm_example_frame.xml")
    if not xml.exists():
        xml = next(Path("tests/fixtures").glob("*example_frame*.xml"))
    original = etree.parse(str(xml)).find("COMPONENT")
    assert original is not None
    component = parse_component_node(original)
    apply_field_default_inheritance(tmp_path, "example", [component])
    source = folder / f"{component.name}.w4gl"
    source.write_text(encode_w4gl(component))
    source.with_suffix(".wml").write_text(encode_wml(component) or "")
    write_companions(xml, folder)
    assert not (tmp_path / ".openroad").exists()
    assert signature(restore_component(source)) == signature(original)
    source.with_suffix(".wml").write_text("<frame />")
    with pytest.raises(ProjectError, match="markup edits"):
        restore_component(source)


def test_preserves_opaque_properties_and_overlays_script(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    xml = tmp_path / "export.xml"
    xml.write_text(
        """<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><COMPONENT name="proc" xsi:type="proc4glsource"><script><![CDATA[PROCEDURE proc() = { RETURN 1; }]]></script><datatype>integer</datatype><queries><row><opaque>keep me</opaque></row></queries></COMPONENT></OPENROAD>"""
    )
    original = etree.parse(str(xml)).find("COMPONENT")
    assert original is not None
    source = folder / "proc.w4gl"
    source.write_text(
        encode_w4gl(parse_component_node(original)).replace("RETURN 1", "RETURN 2")
    )
    write_companions(xml, folder)
    xml.unlink()
    restored = restore_component(source)
    assert restored.findtext("queries/row/opaque") == "keep me"
    assert "RETURN 2" in restored.findtext("script", "")


def test_unknown_format_rejected(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    companion = folder / ".gorak-source"
    companion.mkdir()
    (companion / "components").mkdir()
    (companion / "components" / "proc.xml").write_text("<OPENROAD/>")
    (companion / "format").write_text("999")
    with pytest.raises(ProjectError, match="format"):
        restore_component(folder / "proc.w4gl")


def test_application_named_component_cannot_overwrite_app_metadata(
    tmp_path: Path,
) -> None:
    xml = tmp_path / "export.xml"
    xml.write_text(
        """<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><APPLICATION name="example"><commandline>preserve</commandline></APPLICATION><COMPONENT name="application" xsi:type="globsource"><datatype>integer</datatype></COMPONENT></OPENROAD>"""
    )
    folder = tmp_path / "example"
    folder.mkdir()
    write_companions(xml, folder)
    assert (folder / ".gorak-source/application.xml").is_file()
    assert (folder / ".gorak-source/components/application.xml").is_file()


def test_unknown_top_level_xml_is_rejected(tmp_path: Path) -> None:
    xml = tmp_path / "export.xml"
    xml.write_text("<OPENROAD><UNKNOWN>must not disappear</UNKNOWN></OPENROAD>")
    with pytest.raises(ProjectError, match="top-level"):
        write_companions(xml, tmp_path)

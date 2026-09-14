from pathlib import Path

import pytest
from lxml import etree

from gorak.export import apply_field_default_inheritance
from gorak.importer import signature
from gorak.parser import encode_w4gl, encode_wml, parse_component_node
from gorak.portable_source import legacy_component as restore_component
from gorak.portable_source import write_companions
from gorak.project import ProjectError


@pytest.mark.parametrize("legacy", [False, True])
def test_frame_reconstruction_from_companion_or_legacy_cache(
    tmp_path: Path, legacy: bool
) -> None:
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
    if legacy:
        cache = tmp_path / ".openroad/example"
        cache.mkdir(parents=True)
        (cache / "example.xml").write_bytes(xml.read_bytes())
    else:
        write_companions(xml, folder)
        assert not (tmp_path / ".openroad").exists()
    assert signature(restore_component(source)) == signature(original)
    source.with_suffix(".wml").write_text("<frame />")
    with pytest.raises(ProjectError, match="topform"):
        restore_component(source)


def test_drops_unsupported_queries_and_overlays_script(tmp_path: Path) -> None:
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
    assert restored.find("queries") is None
    assert "RETURN 2" in restored.findtext("script", "")


def test_unknown_format_rejected(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    companion = folder / ".gorak-source"
    companion.mkdir()
    (companion / "components").mkdir()
    (companion / "components" / "proc.xml").write_text("<OPENROAD/>")
    (companion / "format").write_text("999")
    (folder / "proc.w4gl").write_text("[proc4glsource]\n===\nRETURN 1;")
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


@pytest.mark.parametrize(
    "kind",
    ["classsource", "globsource", "proc3glsource", "scriptsource", "ghostsource"],
)
def test_legacy_scriptless_exports_are_not_new_components(
    tmp_path: Path, kind: str
) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    cache = tmp_path / ".openroad/example"
    cache.mkdir(parents=True)
    xml = cache / "item.xml"
    xml.write_text(
        f'<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><COMPONENT name="item" xsi:type="{kind}"><extension><opaque>preserve</opaque></extension></COMPONENT></OPENROAD>'
    )
    original = etree.parse(str(xml)).find("COMPONENT")
    assert original is not None
    source = folder / "item.w4gl"
    source.write_text(encode_w4gl(parse_component_node(original)))
    assert signature(restore_component(source)) == signature(original)
    assert not (folder / ".gorak-source").exists()


def test_legacy_cache_keeps_real_script_changes(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    cache = tmp_path / ".openroad/example"
    cache.mkdir(parents=True)
    xml = cache / "item.xml"
    xml.write_text(
        '<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><COMPONENT name="item" xsi:type="proc4glsource"><script>PROCEDURE item() = { RETURN 1; }</script><extension><opaque>keep</opaque></extension></COMPONENT></OPENROAD>'
    )
    original = etree.parse(str(xml)).find("COMPONENT")
    assert original is not None
    source = folder / "item.w4gl"
    source.write_text(
        encode_w4gl(parse_component_node(original)).replace("RETURN 1", "RETURN 2")
    )
    actual = restore_component(source)
    assert "RETURN 2" in actual.findtext("script", "")
    assert actual.findtext("extension/opaque") == "keep"

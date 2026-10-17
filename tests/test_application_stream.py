from pathlib import Path

import pytest
from lxml import etree

from gorak import source_xml
from gorak.importer import signature
from gorak.project import ProjectError


def test_stream_preserves_text_pi_cdata_attributes_and_order(tmp_path: Path) -> None:
    p = tmp_path / "app.xml"
    p.write_bytes(b"""<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<APPLICATION name="example"/><COMPONENT name="one" xsi:type="proc4glsource"><script><![CDATA[a < b]]><?gorak code?> tail </script><!--keep--><value v="&amp;"/></COMPONENT><COMPONENT name="two"/>
</OPENROAD>""")
    expected = [signature(n) for n in source_xml.read_tree(p).getroot()]
    actual = []
    for node in source_xml.application_children(p):
        assert node.getparent() is None
        actual.append(signature(node))
    assert actual == expected


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_stream_matches_full_parser_newlines_without_changing_references(
    tmp_path: Path, newline: str
) -> None:
    p = tmp_path / "app.xml"
    content = (
        f"<![CDATA[Ä < Ö{newline}Ü]]>&#13;\n"
        f"<?ingres_invalidxmlchar 7?><![CDATA[ß{newline}Größe]]>"
        f"<!--keep-->tail{newline}text"
    )
    p.write_bytes(
        (
            '<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<APPLICATION name="example"><remarks>'
            f"{content}</remarks></APPLICATION>"
            '<COMPONENT name="panel" xsi:type="framesource">'
            f"<script>{content}</script><topform><script>{content}</script></topform>"
            f"<fielddefaults><row><script>{content}</script></row></fielddefaults>"
            '<value v="explicit&#13;reference">literal&#13;reference</value>'
            "</COMPONENT></OPENROAD>"
        ).encode()
    )
    expected = list(source_xml.read_tree(p).getroot())
    actual = list(source_xml.application_children(p))
    assert [signature(n) for n in actual] == [signature(n) for n in expected]
    assert all(n.getparent() is None for n in actual)
    assert actual[1].findtext("value") == "literal\rreference"
    assert actual[1].find("value").get("v") == "explicit\rreference"
    from gorak.xml_text import text_value

    assert text_value(actual[1].find("script")) == (
        "Ä < Ö\nÜ\r\n\x07ß\nGrößetail\ntext"
    )


def test_stream_export_has_clean_status_and_preserves_real_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import export, sync_plan
    from gorak.connection import OpenRoadConnection
    from gorak.domain import ComponentInfo
    from gorak.portable_source import restore_component
    from gorak.xml_text import text_value

    native = tmp_path / "native.xml"
    native.write_bytes(
        b'<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        b'<APPLICATION name="example"/>'
        b'<COMPONENT name="panel" xsi:type="framesource">'
        b"<script><![CDATA[initialize =\r\n{\r\n}\r\n]]></script>"
        b'<fielddefaults><row xsi:type="matrixfield"><clienttext>buttonfield</clienttext>'
        b'<childfields><row xsi:type="buttonfield">'
        b"<script><![CDATA[on click =\r\n{\r\nreturn 3;\r\n}]]></script>"
        b"</row></childfields></row></fielddefaults>"
        b'<topform><childfields><row xsi:type="buttonfield"><name>go</name>'
        b"<script><![CDATA[on click =\r\n{\r\nreturn 1;\r\n}]]></script>"
        b"<textlabel>explicit&#13;reference</textlabel>"
        b"</row></childfields></topform></COMPONENT></OPENROAD>"
    )
    root = tmp_path / "project"
    connection = OpenRoadConnection("local", "node", "db", None)
    monkeypatch.setattr(
        export,
        "read_components",
        lambda *args: [ComponentInfo("example", "panel", "framesource", "")],
    )
    result = export.export_application_to_paths(
        connection,
        "example",
        export.ApplicationExportPaths(
            root / ".openroad/example/example.xml", root / "example"
        ),
        None,
        native_xml=native,
    )
    assert not result.failures
    source = root / "example/panel.w4gl"
    restored = restore_component(source)
    assert text_value(restored.find("topform/childfields/row/script")) == (
        "on click =\n{\nreturn 1;\n}"
    )
    assert text_value(restored.find("fielddefaults/row/childfields/row/script")) == (
        "on click =\n{\nreturn 3;\n}"
    )
    assert restored.findtext("topform/childfields/row/textlabel") == (
        "explicit\rreference"
    )
    native_inventory = sync_plan.xml_inventory(
        source_xml.read_tree(native).getroot(), "example"
    )
    database_hashes = sync_plan.semantic_hashes(native_inventory)
    changes = sync_plan.plan_project(connection, root, database_hashes=database_hashes)
    assert len(changes) == 2
    assert all(c.action == "unchanged" for c in changes)

    markup = source.with_suffix(".wml")
    markup.write_text(
        markup.read_text(encoding="utf-8").replace("return 1;", "return 2;"),
        encoding="utf-8",
    )
    changes = sync_plan.plan_project(connection, root, database_hashes=database_hashes)
    assert next(c for c in changes if c.key == "example/panel").action == "push"


@pytest.mark.parametrize(
    "xml",
    [
        '<!DOCTYPE OPENROAD [<!ENTITY x "abc">]><OPENROAD><APPLICATION/></OPENROAD>',
        "<other><APPLICATION/></other>",
        "<OPENROAD><unknown/></OPENROAD>",
        "<OPENROAD><!--top level--><APPLICATION/></OPENROAD>",
        "<OPENROAD><?top level?><APPLICATION/></OPENROAD>",
    ],
)
def test_stream_rejects_unsupported_documents(tmp_path: Path, xml: str) -> None:
    p = tmp_path / "app.xml"
    p.write_text(xml)
    with pytest.raises(ProjectError):
        list(source_xml.application_children(p))


def test_stream_enforces_depth_and_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "app.xml"
    p.write_text("<OPENROAD><COMPONENT><value/></COMPONENT></OPENROAD>")
    monkeypatch.setattr(source_xml, "MAX_DEPTH", 2)
    with pytest.raises(ProjectError, match="nesting"):
        list(source_xml.application_children(p))
    monkeypatch.setattr(source_xml, "MAX_DOCUMENT_BYTES", 2)
    with pytest.raises(ProjectError, match="document limit"):
        list(source_xml.application_children(p))


def test_export_validates_late_damage_before_projecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import export
    from gorak.connection import OpenRoadConnection

    p = tmp_path / "download.xml"
    p.write_text(
        '<OPENROAD><APPLICATION name="example"/><COMPONENT name="one"/><broken>'
    )
    monkeypatch.setattr(
        export,
        "project_component_files",
        lambda *a, **k: pytest.fail("Projected before validation"),
    )
    with pytest.raises(etree.XMLSyntaxError):
        export.export_application_to_paths(
            OpenRoadConnection("local", "node", "db", None),
            "example",
            export.ApplicationExportPaths(tmp_path / "cache/app.xml", tmp_path / "app"),
            None,
            native_xml=p,
        )

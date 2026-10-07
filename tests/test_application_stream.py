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

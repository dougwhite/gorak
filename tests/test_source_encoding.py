"""Readable sources stay UTF-8 even on a CP1252 Windows installation."""

from pathlib import Path

import pytest
from lxml import etree

from gorak.component_defaults import encode_source_w4gl
from gorak.parser import parse_component_node
from gorak.portable_source import overlay_component, restore_component
from gorak.xml_writer import document, new_application


@pytest.fixture
def cp1252_default(monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.read_text

    def read_text(
        self: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        return original(self, encoding=encoding or "cp1252", errors=errors)

    monkeypatch.setattr(Path, "read_text", read_text)


@pytest.mark.parametrize("kind", ["framesource", "classsource", "proc4glsource"])
def test_utf8_source_under_cp1252_default(
    tmp_path: Path, cp1252_default: None, kind: str
) -> None:
    label = "ÄÖÜ äöü ß – Größe"
    node = etree.Element("COMPONENT", name="sample")
    node.set("{http://www.w3.org/2001/XMLSchema-instance}type", kind)
    etree.SubElement(node, "versshortremarks").text = label
    etree.SubElement(node, "script").text = f"/* {label} */"
    if kind == "framesource":
        etree.SubElement(node, "frmflow").text = r"C:\forms\Größe\sample.flow"
    component = parse_component_node(node)
    source = tmp_path / "sample.w4gl"
    source.write_text(encode_source_w4gl(component), encoding="utf-8")
    if kind == "framesource":
        flow = etree.fromstring(component.markup).find("frmflow")
        flow_xml = etree.tostring(flow, encoding="unicode", with_tail=False)
        source.with_suffix(".wml").write_text(
            f'<frame><topform><buttonfield name="action" '
            f'textlabel="{label}"/></topform>{flow_xml}</frame>',
            encoding="utf-8",
        )
    for restored in (restore_component(source), overlay_component(node, source)):
        assert restored.findtext("versshortremarks") == label
        assert label in restored.findtext("script", "")
        if kind == "framesource":
            assert restored.findtext("frmflow") == r"C:\forms\Größe\sample.flow"
            assert restored.findtext(".//textlabel") == label
        submitted = etree.fromstring(document([restored]))
        assert submitted.findtext("COMPONENT/versshortremarks") == label


def test_utf8_application_metadata_under_cp1252_default(
    tmp_path: Path, cp1252_default: None
) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text('{"description": "Größe"}', encoding="utf-8")
    assert new_application(folder).findtext("versshortremarks") == "Größe"


def test_icon_native_path_and_asset_origins_under_cp1252_default(
    tmp_path: Path, cp1252_default: None
) -> None:
    from PIL import Image

    from gorak.bitmap_codec import decode
    from gorak.image_assets import AssetWriter

    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", (2, 2), "red").save(images / "window.png")
    native_path = r"C:\resources\Größe\window.ico"
    source = tmp_path / "sample.w4gl"
    source.write_text(
        '[framesource]\nwindowicon = { src = "images/window.png", '
        f"path = '{native_path}' }}\n",
        encoding="utf-8",
    )
    source.with_suffix(".wml").write_text("<frame><topform/></frame>", encoding="utf-8")
    restored = restore_component(source)
    assert decode(restored.findtext("windowicon/obj_encoded", "")).origin == native_path
    assert AssetWriter(tmp_path).origins["images/window.png"] == {native_path}

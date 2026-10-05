"""Frame templates retain their native identity and editable frame contents."""

from pathlib import Path

import pytest
from lxml import etree

from gorak.audit import audit_component_node
from gorak.component_defaults import encode_source_w4gl, write_component_defaults
from gorak.contract_source import decode_component, equivalent
from gorak.export import apply_field_default_inheritance
from gorak.parser import NS, parse_component_node
from gorak.portable_source import overlay_component
from gorak.style_commands import describe, maintain

XSI = f"{{{NS['xsi']}}}type"


def export_template(root: Path, node: etree._Element) -> Path:
    folder = root / "example"
    folder.mkdir(exist_ok=True)
    (folder / "app.json").write_text("{}")
    component = parse_component_node(node)
    assert component.markup is not None
    apply_field_default_inheritance(root, "example", [component], source_nodes=[node])
    path = folder / "template.w4gl"
    path.write_text(encode_source_w4gl(component))
    path.with_suffix(".wml").write_text(component.markup)
    write_component_defaults(path, component.props["fielddefaults"])
    return path


@pytest.fixture
def template() -> etree._Element:
    return etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}" name="template" xsi:type="frametemplate">
      <script>initialize()={{}}</script>
      <templatename>empty_frame</templatename>
      <startmenu><name>menu</name><childmenufields>
        <row xsi:type="menubutton"><name>help</name><script>ON CLICK = {{ return; }}</script><textlabel>Help</textlabel></row>
        <row_class>menufield</row_class>
      </childmenufields></startmenu>
      <topform><childfields><row xsi:type="buttonfield"><name>go</name><fieldstyle>0</fieldstyle><textlabel>Go</textlabel></row><row_class>formfield</row_class></childfields></topform>
      <mainbartop><row><name>toolbar</name></row><row_class>mainbar</row_class></mainbartop>
      <fielddefaults/>
      <assistantproc>build_screen</assistantproc>
    </COMPONENT>''')


def test_template_round_trip_and_edit(tmp_path: Path, template: etree._Element) -> None:
    path = export_template(tmp_path, template)
    restored = decode_component(path)
    assert restored.get(XSI) == "frametemplate"
    assert restored.findtext("assistantproc") == "build_screen"
    assert restored.findtext("templatename") == "empty_frame"
    assert (
        restored.findtext("startmenu/childmenufields/row/script")
        == "ON CLICK = { return; }"
    )
    assert restored.findtext("topform/childfields/row/fieldstyle") == "0"
    assert restored.findtext("mainbartop/row/name") == "toolbar"
    assert equivalent(template, restored)
    (tmp_path / "gorak.json").write_text("{}")
    maintain(tmp_path, "compact")
    assert equivalent(restored, decode_component(path))
    assert audit_component_node(restored)["missing_paths"] == []
    assert describe(tmp_path, "example", "template")["stylesheet"] is not None
    wml = path.with_suffix(".wml")
    wml.write_text(wml.read_text().replace('textlabel="Go"', 'textlabel="Run"'))
    edited = overlay_component(restored, path)
    assert edited.findtext("topform/childfields/row/textlabel") == "Run"
    assert edited.get(XSI) == "frametemplate"


def test_template_requires_layout(tmp_path: Path) -> None:
    from gorak.errors import ProjectError

    path = tmp_path / "template.w4gl"
    path.write_text('[frametemplate]\nassistantproc="build_screen"\n')
    with pytest.raises(ProjectError, match="requires a WML"):
        decode_component(path)

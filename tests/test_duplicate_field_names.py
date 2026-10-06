"""Source preserves duplicate names; native compilation diagnoses collisions."""

from pathlib import Path

import pytest
from lxml import etree

from gorak.contract_source import equivalent
from gorak.parser import NS
from gorak.portable_source import overlay_component, restore_component
from tests.native_source import write_component


@pytest.mark.parametrize("kind", ["framesource", "frametemplate", "fieldtemplate"])
@pytest.mark.parametrize("middle", [None, "", "middle"])
def test_duplicate_names_keep_order_identity_and_scripts(
    tmp_path: Path, kind: str, middle: str | None
) -> None:
    node = etree.Element("COMPONENT", name="sample", nsmap=NS)
    xsi = f"{{{NS['xsi']}}}type"
    node.set(xsi, kind)
    top = etree.SubElement(node, "framefield" if kind == "fieldtemplate" else "topform")
    if kind == "fieldtemplate":
        top.set(xsi, "flexibleform")
    rows = etree.SubElement(top, "childfields")
    for i, label in enumerate(("First", "Second")):
        container = rows
        if i == 0 and middle is not None:
            wrapper = etree.SubElement(rows, "row")
            wrapper.set(xsi, "stackfield")
            if middle:
                etree.SubElement(wrapper, "name").text = middle
            container = etree.SubElement(wrapper, "childfields")
        field = etree.SubElement(container, "row")
        field.set(xsi, "buttonfield")
        etree.SubElement(field, "name").text = "child"
        etree.SubElement(field, "textlabel").text = label
        etree.SubElement(field, "script").text = f"on click = {{ /* {label} */ }}"
        if container is not rows:
            etree.SubElement(container, "row_class").text = "formfield"
    etree.SubElement(rows, "row_class").text = "formfield"
    source = tmp_path / "sample.w4gl"
    write_component(source, node)
    restored = restore_component(source)
    assert equivalent(node, restored)
    fields = restored.findall(".//row[name='child']")
    assert [f.findtext("textlabel") for f in fields] == ["First", "Second"]
    assert "First" in fields[0].findtext("script")
    assert "Second" in fields[1].findtext("script")
    wml = source.with_suffix(".wml")
    wml.write_text(wml.read_text().replace('textlabel="Second"', 'textlabel="Edited"'))
    overlay_component(node, source)
    assert [f.findtext("textlabel") for f in node.findall(".//row[name='child']")] == [
        "First",
        "Edited",
    ]


def test_duplicate_menu_names_survive(tmp_path: Path) -> None:
    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}" name="sample" xsi:type="framesource">
      <startmenu><childmenufields>
        <row xsi:type="menulist"><name>choice</name><clienttext>First</clienttext><script>on click = {{}}</script></row>
        <row xsi:type="menulist"><name>choice</name><clienttext>Second</clienttext><script>on click = {{ /* second */ }}</script></row>
        <row_class>menufield</row_class>
      </childmenufields></startmenu><topform/></COMPONENT>''')
    source = tmp_path / "sample.w4gl"
    write_component(source, node)
    assert equivalent(node, restore_component(source))

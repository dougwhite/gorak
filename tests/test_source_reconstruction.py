"""The current unversioned contract reconstructs native source without caches."""

from pathlib import Path

import pytest
from lxml import etree

from gorak.component_edits import SUPPORTED_TYPES
from gorak.contract_source import equivalent
from gorak.portable_source import restore_component
from gorak.xml_shapes import order_children
from tests.native_source import write_component


@pytest.mark.parametrize(
    "fixture",
    [
        "fm_example_frame",
        "fm_complex_frame",
        "uc_example_userclass",
        "p4_example_procedure",
    ],
)
def test_current_fixture_without_cache(tmp_path: Path, fixture: str) -> None:
    original = etree.parse(f"tests/fixtures/{fixture}.xml").find("COMPONENT")
    assert original is not None
    folder = tmp_path / "example"
    folder.mkdir()
    source = folder / (original.get("name") + ".w4gl")
    write_component(source, original)
    assert equivalent(original, restore_component(source))
    for directory in [
        tmp_path / ".openroad/example",
        folder / ".gorak-source/components",
    ]:
        directory.mkdir(parents=True)
        (directory / (source.stem + ".xml")).write_text("invalid ignored source")
    assert equivalent(original, restore_component(source))


@pytest.mark.parametrize("kind", sorted(SUPPORTED_TYPES))
def test_each_supported_type(tmp_path: Path, kind: str) -> None:
    node = etree.Element("COMPONENT", name="sample")
    node.set("{http://www.w3.org/2001/XMLSchema-instance}type", kind)
    etree.SubElement(node, "versshortremarks").text = "metadata survives"
    if kind in {"framesource", "frametemplate"}:
        etree.SubElement(node, "fielddefaults")
        etree.SubElement(node, "topform")
    order_children(node, kind)
    folder = tmp_path / "example"
    folder.mkdir()
    source = folder / "sample.w4gl"
    write_component(source, node)
    assert equivalent(node, restore_component(source))


@pytest.mark.parametrize("kind", ["entryfield", "buttonfield", "togglefield"])
def test_native_prototype_type_and_matrix_position_are_explicit(
    tmp_path: Path, kind: str
) -> None:
    node = etree.fromstring(
        f'''<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="sample" xsi:type="framesource"><fielddefaults/><topform><childfields><row xsi:type="matrixfield" row="2" column="3"><childfields><row xsi:type="columnfield"><protofield xsi:type="{kind}"><name>value</name><width>100</width></protofield></row><row_class>formfield</row_class></childfields></row><row_class>formfield</row_class></childfields></topform></COMPONENT>'''
    )
    folder = tmp_path / "example"
    folder.mkdir()
    source = folder / "sample.w4gl"
    write_component(source, node)
    markup = source.with_suffix(".wml").read_text()
    assert f'type="{kind}"' in markup
    assert 'row="2"' in markup and 'column="3"' in markup
    restored = restore_component(source)
    assert restored.find("topform/childfields/row").get("row") == "2"
    assert (
        restored.find(".//protofield").get(
            "{http://www.w3.org/2001/XMLSchema-instance}type"
        )
        == kind
    )
    assert equivalent(node, restored)

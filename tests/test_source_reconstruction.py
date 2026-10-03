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
    if kind == "framesource":
        etree.SubElement(node, "fielddefaults")
        etree.SubElement(node, "topform")
    order_children(node, kind)
    folder = tmp_path / "example"
    folder.mkdir()
    source = folder / "sample.w4gl"
    write_component(source, node)
    assert equivalent(node, restore_component(source))

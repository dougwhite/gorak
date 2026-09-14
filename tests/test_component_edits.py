from pathlib import Path

import pytest
from lxml import etree

from gorak.component_edits import overlay_metadata
from gorak.parser import NS, encode_w4gl, parse_component_node


@pytest.mark.parametrize(
    "kind",
    [
        "classsource",
        "proc4glsource",
        "globsource",
        "proc3glsource",
        "scriptsource",
        "ghostsource",
        "framesource",
        "constsource",
    ],
)
def test_description_edits_preserve_opaque_xml(tmp_path: Path, kind: str) -> None:
    node = etree.Element("COMPONENT", name="example", nsmap=NS)
    node.set(f"{{{NS['xsi']}}}type", kind)
    etree.SubElement(node, "versshortremarks").text = "Before"
    opaque = etree.SubElement(node, "extension")
    etree.SubElement(opaque, "opaque", keep="yes")
    source = tmp_path / "example.w4gl"
    source.write_text(
        encode_w4gl(parse_component_node(node)).replace("Before", "After")
    )
    overlay_metadata(node, source)
    assert node.findtext("versshortremarks") == "After"
    assert node.find("extension/opaque").get("keep") == "yes"


def test_class_declarations_preserve_existing_row_metadata(tmp_path: Path) -> None:
    node = etree.fromstring(
        b"""<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="example" xsi:type="classsource"><superclass>object</superclass><script>METHOD compute()={}</script><attributes><row><displayname>quantity</displayname><datatype>integer</datatype><defaultvalue>3</defaultvalue><defaultstring>7</defaultstring></row><row_class>attributeobject</row_class></attributes><methods><row><displayname>compute</displayname></row><row_class>methodobject</row_class></methods></COMPONENT>"""
    )
    source = tmp_path / "example.w4gl"
    source.write_text(
        encode_w4gl(parse_component_node(node))
        .replace(
            'quantity = "INTEGER NOT NULL"',
            'quantity = "FLOAT NOT NULL"\nlabel = "VARCHAR(32)"',
        )
        .replace(
            'compute = "METHOD"',
            'compute = "PRIVATE METHOD RETURNING INTEGER NOT NULL"',
        )
    )
    overlay_metadata(node, source)
    assert node.findtext("attributes/row/datatype") == "float"
    assert node.findtext("attributes/row/defaultstring") == "7"
    assert len(node.findall("attributes/row")) == 2
    assert node.findtext("methods/row/isprivate") == "1"
    assert node.findtext("methods/row/datatype") == "integer"

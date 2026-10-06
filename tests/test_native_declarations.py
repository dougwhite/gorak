"""Native type syntax and attribute names survive readable reconstruction."""

from pathlib import Path

import pytest
from lxml import etree

from gorak.contract_source import equivalent
from gorak.errors import ProjectError
from gorak.importer import validate_name
from gorak.parser import NS
from gorak.portable_source import restore_component
from gorak.xml_writer import datatype
from tests.native_source import write_component


@pytest.mark.parametrize("type_name", ["shared!uc_item", "long byte"])
@pytest.mark.parametrize("array", [False, True])
@pytest.mark.parametrize("nullable", [False, True])
def test_native_type_declaration_roundtrip(
    tmp_path: Path, type_name: str, array: bool, nullable: bool
) -> None:
    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}" name="sample" xsi:type="classsource">
        <attributes><row><displayname>value</displayname><datatype>{type_name}</datatype></row>
        <row_class>attributeobject</row_class></attributes></COMPONENT>''')
    row = node.find("attributes/row")
    if array:
        etree.SubElement(row, "isarray").text = "1"
    if nullable:
        etree.SubElement(row, "isnullable").text = "1"
    source = tmp_path / "sample.w4gl"
    write_component(source, node)
    assert type_name.upper() in source.read_text()
    assert equivalent(node, restore_component(source))


def test_qualified_method_return_and_explicit_null(tmp_path: Path) -> None:
    source = tmp_path / "sample.w4gl"
    source.write_text("""[classsource]
[attributes]
item = "SHARED!UC_ITEM DEFAULT NULL"
[methods]
items = "PRIVATE METHOD RETURNING ARRAY OF SHARED!UC_ITEM NOT NULL"
""")
    node = restore_component(source)
    assert node.findtext("attributes/row/datatype") == "shared!uc_item"
    assert node.findtext("attributes/row/defaultvalue") == "2"
    assert node.findtext("methods/row/datatype") == "shared!uc_item"
    assert node.findtext("methods/row/isarray") == "1"
    assert node.findtext("methods/row/isprivate") == "1"


def test_dollar_attribute_names_keep_exact_spelling(tmp_path: Path) -> None:
    from gorak.portable_source import overlay_component

    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}" name="sample" xsi:type="classsource">
        <attributes><row><displayname>p1_$T</displayname><datatype>float</datatype></row>
        <row><displayname>total_$t_actual</displayname><datatype>integer</datatype></row>
        <row_class>attributeobject</row_class></attributes></COMPONENT>''')
    source = tmp_path / "sample.w4gl"
    write_component(source, node)
    assert '"p1_$T"' in source.read_text()
    assert equivalent(node, restore_component(source))
    source.write_text(source.read_text().replace("p1_$T", "p2_$T"))
    overlay_component(node, source)
    assert node.findtext("attributes/row/displayname") == "total_$t_actual"
    assert node.find("attributes/row[displayname='p2_$T']") is not None
    with pytest.raises(ProjectError):
        validate_name("p2_$T")


@pytest.mark.parametrize(
    "declaration",
    [
        "APP!!CLASS",
        "APP!",
        "!CLASS",
        "APP!CLASS(2)",
        "LONG UNKNOWN",
        "APP!CLASS EXTRA",
        "APP/CLASS",
        "ARRAY OF ARRAY OF INTEGER",
    ],
)
def test_malformed_types_are_refused(declaration: str) -> None:
    with pytest.raises(ProjectError, match="Unsupported type declaration"):
        datatype(etree.Element("row"), declaration)


@pytest.mark.parametrize(
    "name", ["$T", "1bad", "has space", "path/name", "x;command", "x" * 33]
)
def test_attribute_names_remain_bounded(name: str) -> None:
    from gorak.component_edits import validate_attribute_name

    with pytest.raises(ProjectError, match="attribute name"):
        validate_attribute_name(name)

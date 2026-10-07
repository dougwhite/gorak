"""Independent native-field assertions for compact and structured declarations."""

import tomllib
from pathlib import Path

import pytest
from lxml import etree

from gorak.component_edits import overlay_metadata
from gorak.errors import ProjectError
from gorak.parser import NS, encode_w4gl, parse_component_node
from gorak.portable_source import restore_component
from gorak.xml_text import set_text, text_value
from tests.native_source import write_component


def component() -> etree._Element:
    return etree.Element(
        "COMPONENT", name="sample", attrib={f"{{{NS['xsi']}}}type": "classsource"}
    )


def member(
    node: etree._Element, table: str = "attributes", name: str = "value", **fields: str
) -> etree._Element:
    container = node.find(table)
    if container is None:
        container = etree.SubElement(node, table)
    row = etree.SubElement(container, "row")
    for key, value in {"displayname": name, **fields}.items():
        set_text(etree.SubElement(row, key), value)
    return row


def roundtrip(tmp_path: Path, node: etree._Element) -> tuple[str, etree._Element]:
    path = tmp_path / "sample.w4gl"
    write_component(path, node)
    return path.read_text(), restore_component(path)


@pytest.mark.parametrize(
    "value", ["", "today", "3", "O'Reilly", "a\\b", "line\nnext", "\x07"]
)
def test_default_literals_are_preserved_independently(
    tmp_path: Path, value: str
) -> None:
    node = component()
    member(
        node,
        datatype="varchar(80)",
        defaultvalue="3",
        defaultstring=value,
        isprivate="1",
    )
    source, restored = roundtrip(tmp_path, node)
    declaration = tomllib.loads(source)["attributes"]["value"]
    assert isinstance(declaration, str)
    assert declaration.startswith("PRIVATE VARCHAR(80) NOT NULL DEFAULT ")
    row = restored.find("attributes/row")
    assert row.findtext("defaultvalue") == "3"
    assert text_value(row.find("defaultstring")) == value
    assert row.findtext("isprivate") == "1"


@pytest.mark.parametrize(
    "dtype,array",
    [
        ("integer", False),
        ("sample_class", False),
        ("sample_class", True),
        ("integer", True),
    ],
)
@pytest.mark.parametrize("mode", [None, "1", "2", "3"])
def test_nullability_and_default_source_are_independent(
    tmp_path: Path, dtype: str, array: bool, mode: str | None
) -> None:
    fields = {"datatype": dtype, "isnullable": "1"}
    if array:
        fields["isarray"] = "1"
    if mode:
        fields["defaultvalue"] = mode
    if mode == "3":
        fields["defaultstring"] = "3"
    node = component()
    member(node, **fields)
    source, restored = roundtrip(tmp_path, node)
    declaration = tomllib.loads(source)["attributes"]["value"]
    assert "NOT NULL" not in declaration
    row = restored.find("attributes/row")
    assert row.findtext("isnullable") == "1"
    assert row.findtext("defaultvalue", "1") == (mode or "1")
    assert ("DEFAULT NULL" in declaration) == (mode == "2")
    assert ("DEFAULT '3'" in declaration) == (mode == "3")


def test_implicit_reference_nullability_and_empty_literal(tmp_path: Path) -> None:
    node = component()
    member(node, datatype="shared!item", defaultvalue="3")
    source, restored = roundtrip(tmp_path, node)
    assert tomllib.loads(source)["attributes"]["value"] == "SHARED!ITEM DEFAULT ''"
    assert restored.findtext("attributes/row/isnullable") == "1"
    assert restored.findtext("attributes/row/defaultstring") == ""


@pytest.mark.parametrize("mode", [None, "1", "2"])
def test_inactive_default_string_does_not_become_active(
    tmp_path: Path, mode: str | None
) -> None:
    node = component()
    row = member(node, datatype="integer", isnullable="1", defaultstring="7")
    if mode:
        etree.SubElement(row, "defaultvalue").text = mode
    source, restored = roundtrip(tmp_path, node)
    value = tomllib.loads(source)["attributes"]["value"]
    assert value["defaultstring"] == "7"
    assert "DEFAULT '7'" not in value["declaration"]
    assert restored.findtext("attributes/row/defaultvalue", "1") == (mode or "1")
    assert restored.findtext("attributes/row/defaultstring") == "7"


@pytest.mark.parametrize("table", ["attributes", "methods"])
def test_remarks_and_ordered_duplicate_tags_survive(tmp_path: Path, table: str) -> None:
    node = component()
    row = member(
        node, table, datatype="integer", remark=" note\n\t\x07 ", isprivate="1"
    )
    tags = etree.SubElement(row, "taggedvalues")
    for value in [" first ", "second\n", "\x07"]:
        tag = etree.SubElement(tags, "row")
        etree.SubElement(tag, "name").text = "same_key"
        set_text(etree.SubElement(tag, "value"), value)
    etree.SubElement(tags, "row_class").text = "taggedvalue"
    source, restored = roundtrip(tmp_path, node)
    data = tomllib.loads(source)[table]["value"]
    assert data["remark"] == " note\n\t\x07 "
    assert [t["value"] for t in data["taggedvalues"]] == [" first ", "second\n", "\x07"]
    row = restored.find(table + "/row")
    assert text_value(row.find("remark")) == data["remark"]
    assert [text_value(v) for v in row.findall("taggedvalues/row/value")] == [
        " first ",
        "second\n",
        "\x07",
    ]
    assert row.findtext("isprivate") == "1"


def test_untyped_method_metadata_does_not_invent_return_type(tmp_path: Path) -> None:
    node = component()
    member(node, "methods", isnullable="1", remark="")
    source, restored = roundtrip(tmp_path, node)
    assert tomllib.loads(source)["methods"]["value"] == {
        "declaration": "METHOD",
        "isnullable": True,
        "remark": "",
    }
    assert restored.find("methods/row/datatype") is None
    assert restored.findtext("methods/row/isnullable") == "1"


def test_structured_and_compact_forms_edit_remove_and_rename_metadata(
    tmp_path: Path,
) -> None:
    node = component()
    member(
        node,
        datatype="integer",
        defaultvalue="3",
        defaultstring="7",
        remark="old",
        isprivate="1",
    )
    source = tmp_path / "sample.w4gl"
    source.write_text('[classsource]\n[attributes]\nvalue = "FLOAT NOT NULL"\n')
    overlay_metadata(node, source)
    row = node.find("attributes/row")
    assert row.findtext("datatype") == "float"
    assert all(
        row.find(k) is None
        for k in ("remark", "isprivate", "defaultvalue", "defaultstring")
    )
    source.write_text(
        '[classsource]\n[attributes]\nrenamed = { declaration="PRIVATE INTEGER DEFAULT NULL", remark="new" }\n'
    )
    overlay_metadata(node, source)
    assert len(node.findall("attributes/row")) == 1
    assert node.findtext("attributes/row/displayname") == "renamed"
    assert node.findtext("attributes/row/remark") == "new"
    assert node.findtext("attributes/row/defaultvalue") == "2"


@pytest.mark.parametrize(
    "extra",
    [
        "<unknown>1</unknown>",
        "<remark>a</remark><remark>b</remark>",
        "<taggedvalues><row><unknown>x</unknown></row></taggedvalues>",
    ],
)
def test_unrepresentable_native_metadata_is_refused(extra: str) -> None:
    node = component()
    row = member(node, datatype="integer")
    row.extend(etree.fromstring("<fields>" + extra + "</fields>"))
    with pytest.raises(ProjectError, match="Unsupported"):
        parse_component_node(node)


@pytest.mark.parametrize(
    "value",
    [
        '{ declaration="INTEGER", surprise=1 }',
        '{ declaration="INTEGER", remark=3 }',
        '{ declaration="INTEGER", taggedvalues=[{name="x", value=1}] }',
        '{ declaration="METHOD RETURNING INTEGER", isnullable=true }',
        '"INTEGER NOT NULL DEFAULT NULL"',
        '"INTEGER DEFAULT unquoted"',
    ],
)
def test_invalid_member_inputs_fail_explicitly(tmp_path: Path, value: str) -> None:
    table = "methods" if "METHOD" in value else "attributes"
    p = tmp_path / "sample.w4gl"
    p.write_text("[classsource]\n[" + table + "]\nvalue = " + value + "\n")
    with pytest.raises(ProjectError):
        restore_component(p)


def test_canonical_export_accepts_both_toml_object_spellings(tmp_path: Path) -> None:
    p = tmp_path / "sample.w4gl"
    p.write_text(
        '[classsource]\n[attributes]\nplain="INTEGER NOT NULL"\n[attributes.rich]\ndeclaration="PRIVATE INTEGER DEFAULT NULL"\nremark="note"\n'
    )
    restored = restore_component(p)
    canonical = encode_w4gl(parse_component_node(restored))
    data = tomllib.loads(canonical)
    assert data["attributes"]["plain"] == "INTEGER NOT NULL"
    assert data["attributes"]["rich"] == {
        "declaration": "PRIVATE INTEGER DEFAULT NULL",
        "remark": "note",
    }


@pytest.mark.parametrize("table", ["attributes", "methods"])
def test_whitespace_member_metadata_uses_native_cdata(
    tmp_path: Path, table: str
) -> None:
    # OpenROAD discards plain XML whitespace here but retains CDATA text.
    node = component()
    row = member(node, table, datatype="varchar(20)", remark="\t\n")
    tags = etree.SubElement(row, "taggedvalues")
    tag = etree.SubElement(tags, "row")
    etree.SubElement(tag, "name").text = "note"
    etree.SubElement(tag, "value").text = " \n"
    etree.SubElement(tags, "row_class").text = "taggedvalue"
    _, restored = roundtrip(tmp_path, node)
    xml = etree.tostring(restored)
    assert b"<remark><![CDATA[\t\n]]></remark>" in xml
    assert b"<value><![CDATA[ \n]]></value>" in xml


@pytest.mark.parametrize("mode", ["1", "3"])
def test_whitespace_default_uses_native_cdata(tmp_path: Path, mode: str) -> None:
    node = component()
    member(node, datatype="varchar(20)", defaultvalue=mode, defaultstring=" ")
    _, restored = roundtrip(tmp_path, node)
    assert b"<defaultstring><![CDATA[ ]]></defaultstring>" in etree.tostring(restored)

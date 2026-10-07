"""Synthetic coverage for full-corpus fidelity failures; no customer fixtures."""

import json
from pathlib import Path

import pytest
from lxml import etree

from gorak import native_styles
from gorak.export import application_metadata
from gorak.import_backend import checked_log
from gorak.native_normalization import signature
from gorak.parser import parse_application_xml
from gorak.portable_source import restore_component
from gorak.project import ProjectError
from gorak.xml_text import text_value
from gorak.xml_writer import new_application
from tests.native_source import write_component

XSI = "http://www.w3.org/2001/XMLSchema-instance"


@pytest.mark.parametrize("value", [" ", "\t", "\n", " leading", "trailing\n", "a&b\n "])
def test_literal_field_text_survives_readable_only_reconstruction(
    tmp_path: Path, value: str
) -> None:
    node = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{XSI}" name="panel" xsi:type="framesource"><topform><childfields><row xsi:type="entryfield"><name>input</name></row><row_class>formfield</row_class></childfields></topform></COMPONENT>'
    )
    field = node.find("topform/childfields/row")
    assert field is not None
    for tag in ["defaultstring", "tooltiptext", "mousedowntext", "mousemovetext"]:
        etree.SubElement(field, tag).text = etree.CDATA(value)
    source = tmp_path / "panel.w4gl"
    write_component(source, node)
    restored = restore_component(source)
    for tag in ["defaultstring", "tooltiptext", "mousedowntext", "mousemovetext"]:
        scalar = restored.find("topform/childfields/row/" + tag)
        assert scalar is not None and text_value(scalar) == value
        assert b"<![CDATA[" in etree.tostring(scalar)


def test_empty_choice_rows_keep_order_and_multiplicity(tmp_path: Path) -> None:
    node = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{XSI}" name="panel" xsi:type="framesource"><topform><childfields><row xsi:type="optionfield"><name>choice</name><valuelist><choiceitems><row/><row><enumtext>middle</enumtext></row><row/><row/><row_class>choicedetail</row_class></choiceitems></valuelist></row><row_class>formfield</row_class></childfields></topform></COMPONENT>'
    )
    source = tmp_path / "panel.w4gl"
    write_component(source, node)
    rows = restore_component(source).findall(
        "topform/childfields/row/valuelist/choiceitems/row"
    )
    assert len(rows) == 4
    assert [row.findtext("enumtext") for row in rows] == [None, "middle", None, None]


def test_appflags_and_core_are_stable(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    value = " first flag\nsecond flag \n"
    (folder / "app.json").write_text(
        json.dumps(
            {"appflags": value, "included_applications": ["alpha", "CORE", "beta"]}
        )
    )
    native = new_application(folder)
    assert native.findtext("appflags") == value
    assert [r.findtext("appname") for r in native.findall("included_apps/row")] == [
        "core",
        "alpha",
        "beta",
    ]
    assert [
        r.findtext("sequence", "0") for r in native.findall("included_apps/row")
    ] == ["0", "1", "2"]
    root = etree.Element("OPENROAD")
    root.append(native)
    parsed = parse_application_xml(root)
    metadata = application_metadata(
        parsed.application, included_applications=parsed.included_applications
    )
    assert metadata["appflags"] == value
    includes = metadata["included_applications"]
    assert isinstance(includes, list) and len(includes) == 2


def test_stylesheet_row_type_notation_is_canonical() -> None:
    implicit = etree.fromstring(
        f'<fielddefaults xmlns:xsi="{XSI}"><row xsi:type="matrixfield"><clienttext>sample</clienttext><childfields><row xsi:type="entryfield"><valuelist><choiceitems><row/><row><enumtext>x</enumtext></row><row_class>choicedetail</row_class></choiceitems></valuelist></row></childfields></row><row_class>formfield</row_class></fielddefaults>'
    )
    explicit = etree.fromstring(etree.tostring(implicit))
    values = explicit.find("row/childfields/row/valuelist/choiceitems")
    assert values is not None
    for row in values.findall("row"):
        row.set(f"{{{XSI}}}type", "choicedetail")
    values.remove(values.find("row_class"))
    assert native_styles.encode(implicit) == native_styles.encode(explicit)
    assert native_styles.encode(
        native_styles.decode(native_styles.encode(implicit))
    ) == native_styles.encode(implicit)


@pytest.mark.parametrize(
    "message",
    [
        "Importing e_example . . . done.",
        "Component e_test imported",
        "Importing failure . . . done.",
    ],
)
def test_import_log_identifiers_are_not_errors(tmp_path: Path, message: str) -> None:
    log = tmp_path / "import.log"
    log.write_text(message)
    checked_log(message)


@pytest.mark.parametrize(
    "message",
    [
        "ERROR: invalid source",
        "E_OR1234 Invalid source",
        "Importing example . . . failed",
    ],
)
def test_import_log_still_rejects_diagnostics(tmp_path: Path, message: str) -> None:
    log = tmp_path / "import.log"
    log.write_text(message)
    with pytest.raises(ProjectError):
        checked_log(message)


def test_tracking_normalization_preserves_literal_text_and_empty_rows() -> None:
    a = etree.fromstring(
        "<COMPONENT><script> body\n</script><defaultvalue>1</defaultvalue><versshortremarks/><values><row/><row> </row><row_class>sample</row_class></values></COMPONENT>"
    )
    b = etree.fromstring(etree.tostring(a))
    b.find("script").text = "body"
    b.remove(b.find("defaultvalue"))
    b.remove(b.find("versshortremarks"))
    assert signature(a) == signature(b)
    b.find("values/row[2]").text = ""
    assert signature(a) != signature(b)


@pytest.mark.parametrize(
    "kind,dimensions",
    [("rectangleshape", ("width", "height")), ("segmentshape", ("width",))],
)
def test_omitted_zero_shape_dimensions_override_native_constructor(
    tmp_path: Path, kind: str, dimensions: tuple[str, ...]
) -> None:
    node = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{XSI}" name="panel" xsi:type="framesource"><topform><childfields><row xsi:type="{kind}"><name>shape</name></row><row_class>formfield</row_class></childfields></topform></COMPONENT>'
    )
    source = tmp_path / "panel.w4gl"
    write_component(source, node)
    field = restore_component(source).find("topform/childfields/row")
    assert field is not None
    for dimension in dimensions:
        assert field.findtext(dimension) == "0"


def test_missing_current_catalog_version_is_never_cached_as_unchanged() -> None:
    from dataclasses import asdict

    from gorak.database import ComponentSyncMetadata
    from gorak.sync_state import component_changed

    item = ComponentSyncMetadata(
        "example", "missing", "framesource", 1, 0, 0, "", 0, "", 0
    )
    assert component_changed(asdict(item), item)


def test_accepted_receipt_is_bound_to_exact_cached_bytes(tmp_path: Path) -> None:
    from gorak.import_receipt import accepted_baseline, is_accepted_baseline

    submitted = tmp_path / "submitted.xml"
    submitted.write_bytes(b"<OPENROAD/>")
    target = tmp_path / "cached.xml"
    for path, data in accepted_baseline(target, submitted, tmp_path).items():
        path.write_bytes(data)
    assert is_accepted_baseline(target)
    target.write_bytes(b"<OPENROAD><APPLICATION/></OPENROAD>")
    assert not is_accepted_baseline(target)


def test_tracking_default_normalization_does_not_discard_unknown_metadata() -> None:
    plain = etree.fromstring(
        "<COMPONENT><defaultvalue>1</defaultvalue><values><row/><row_class>sample</row_class></values></COMPONENT>"
    )
    changed = etree.fromstring(etree.tostring(plain))
    changed.find("defaultvalue").set("extra", "keep")
    changed.find("values/row_class").set("extra", "keep")
    assert signature(plain) != signature(changed)


def test_tracking_keeps_opaque_literal_metadata_exact() -> None:
    original = etree.fromstring(
        "<COMPONENT><extension><script> literal </script><defaultvalue>1</defaultvalue></extension></COMPONENT>"
    )
    changed = etree.fromstring(
        "<COMPONENT><extension><script>literal</script></extension></COMPONENT>"
    )
    assert signature(original) != signature(changed)


def test_macros_without_script_body_keep_native_script_owner(tmp_path: Path) -> None:
    node = etree.fromstring(
        f'<COMPONENT xmlns:xsi="{XSI}" name="panel" xsi:type="framesource"><script/><macro_vars><row><name>$LABEL</name><value>Sample</value><shortremark> </shortremark></row><row_class>macrovariable</row_class></macro_vars><topform/></COMPONENT>'
    )
    source = tmp_path / "panel.w4gl"
    write_component(source, node)
    assert "===" not in source.read_text()
    restored = restore_component(source)
    assert restored.find("script") is not None
    assert restored.findtext("macro_vars/row/value") == "Sample"
    remark = restored.find("macro_vars/row/shortremark")
    assert remark is not None and text_value(remark) == " "
    assert b"<![CDATA[ ]]>" in etree.tostring(remark)
    without_owner = etree.fromstring(etree.tostring(restored))
    without_owner.remove(without_owner.find("script"))
    assert signature(restored) != signature(without_owner)


def test_tracking_property_order_is_distinct_from_collection_order() -> None:
    a = etree.fromstring(
        "<COMPONENT><topform><exactwidth>1</exactwidth><maxcharacters>20</maxcharacters><items><row>A</row><row>B</row></items></topform><extension><a/><b/></extension></COMPONENT>"
    )
    b = etree.fromstring(
        "<COMPONENT><topform><maxcharacters>20</maxcharacters><exactwidth>1</exactwidth><items><row>A</row><row>B</row></items></topform><extension><a/><b/></extension></COMPONENT>"
    )
    assert signature(a) == signature(b)
    rows = b.find("topform/items")
    rows[:] = list(reversed(rows))
    assert signature(a) != signature(b)
    rows[:] = list(reversed(rows))
    opaque = b.find("extension")
    opaque[:] = list(reversed(opaque))
    assert signature(a) != signature(b)

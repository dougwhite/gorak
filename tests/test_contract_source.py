"""The established compact source remains directly importable without migration."""

import json
from pathlib import Path

import pytest
from lxml import etree

from gorak.contract_source import decode_component
from gorak.errors import ProjectError
from gorak.parser import NS, parse_component_node
from gorak.portable_source import comparison_component

XSI = f"{{{NS['xsi']}}}type"


def project(tmp_path: Path) -> Path:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    defaults = {
        "common_model_container": {"type": "matrixfield", "properties": {}},
        "field_styles": [
            {
                "type": "buttonfield",
                "group": "buttonfield",
                "properties": {"bgcolor": "2", "width": "100"},
            }
        ],
    }
    (tmp_path / "field_defaults.json").write_text(json.dumps(defaults))
    (folder / "field_defaults.json").write_text("{}")
    return folder


def test_compact_frame_reconstructs_without_xml_and_preserves_bytes(
    tmp_path: Path,
) -> None:
    folder = project(tmp_path)
    path = folder / "panel.w4gl"
    path.write_text('[framesource]\nwindowtitle = "Example"\n\n===\ninitialize()={}\n')
    path.with_suffix(".wml").write_text(
        '<frame><topform><buttonfield name="go" xleft="500" textlabel="Go"/></topform></frame>'
    )
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    node = decode_component(path)
    field = node.find("topform/childfields/row")
    assert field is not None and field.get(XSI) == "buttonfield"
    assert field.findtext("bgcolor") == "2"
    assert field.findtext("xleft") == "500"
    palette = node.find("fielddefaults/row")
    assert (
        palette is not None
        and palette.findtext("columns") == "1"
        and palette.findtext("rows") == "1"
    )
    assert palette.find("childfields/row").get("row") == "1"
    assert palette.find("childfields/row").get("column") == "1"
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_compact_class_declarations_and_empty_structures(tmp_path: Path) -> None:
    folder = project(tmp_path)
    path = folder / "widget.w4gl"
    path.write_text(
        '[classsource]\nsuperclass="userobject"\nextension=""\nqueries=""\n[attributes]\ncount="INTEGER NOT NULL"\n[methods]\nget_count="METHOD RETURNING INTEGER NOT NULL"\n===\nmethod get_count()={return self.count;}'
    )
    node = decode_component(path)
    assert node.find("extension") is None
    assert node.findtext("attributes/row/datatype") == "integer"
    assert (
        parse_component_node(node).props["methods"]["get_count"]
        == "METHOD RETURNING INTEGER NOT NULL"
    )


def test_comparison_keeps_unrepresented_baseline_metadata(tmp_path: Path) -> None:
    folder = project(tmp_path)
    path = folder / "calculate.w4gl"
    path.write_text('[proc4glsource]\ndatatype="integer"\n===\nreturn 12;')
    cache = tmp_path / ".openroad/example"
    cache.mkdir(parents=True)
    (cache / "calculate.xml").write_text(
        '<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><COMPONENT name="calculate" xsi:type="proc4glsource"><script>return 10;</script><datatype>integer</datatype><extension><row_class>object</row_class></extension></COMPONENT></OPENROAD>'
    )
    # Existing source doesn't expose nonempty extension internals: unchanged
    # projections retain that data, while scripts still produce exact changes.
    path.write_text(
        '[proc4glsource]\ndatatype="integer"\nextension=""\n===\nreturn 12;'
    )
    node = comparison_component(path)
    assert node.findtext("extension/row_class") == "object"
    assert node.findtext("script") == "return 12;"


def test_unknown_frame_property_is_refused(tmp_path: Path) -> None:
    folder = project(tmp_path)
    path = folder / "panel.w4gl"
    path.write_text("[framesource]\n===\ninitialize()={}")
    path.with_suffix(".wml").write_text(
        '<frame><topform><buttonfield invented="yes"/></topform></frame>'
    )
    with pytest.raises(ProjectError, match="Unsupported markup property"):
        decode_component(path)


def test_palette_selection_uses_explicit_differences(tmp_path: Path) -> None:
    folder = project(tmp_path)
    defaults = json.loads((tmp_path / "field_defaults.json").read_text())
    defaults["field_styles"] = [
        {
            "type": "tablefield",
            "group": "tablefield",
            "properties": {"fgcolor": "2", "hasheaderbuttons": "1"},
        },
        {
            "type": "tablefield",
            "group": "tablefield",
            "properties": {"fgcolor": "5", "hasheaderbuttons": "0"},
        },
    ]
    (tmp_path / "field_defaults.json").write_text(json.dumps(defaults))
    path = folder / "panel.w4gl"
    path.write_text("[framesource]\n===\ninitialize()={}")
    path.with_suffix(".wml").write_text(
        '<frame><topform><tablefield name="items" fgcolor="5"/></topform></frame>'
    )
    node = decode_component(path)
    # fgcolor=5 is present precisely because it differs from the first palette.
    assert node.findtext("topform/childfields/row/hasheaderbuttons") == "1"


def test_queries_ignored_in_both_export_and_import(tmp_path: Path) -> None:
    from gorak.parser import encode_w4gl

    folder = project(tmp_path)
    path = folder / "item.w4gl"
    path.write_text(
        '[classsource]\nsuperclass="userobject"\nqueries=""\n===\ninitialize={}\n'
    )
    node = decode_component(path)
    assert node.find("queries") is None
    etree.SubElement(
        etree.SubElement(node, "queries"), "query"
    ).text = "unsupported designer data"
    assert "queries" not in encode_w4gl(parse_component_node(node))


def test_bitmap_transport_line_wrap_does_not_change_readable_source() -> None:
    from gorak.contract_source import equivalent

    source = '<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="panel" xsi:type="framesource"><topform><bgbitmap><obj_encoded>opaque line one\nline two</obj_encoded></bgbitmap></topform></COMPONENT>'
    before = etree.fromstring(source)
    after = etree.fromstring(source.replace("\n", " "))
    assert equivalent(before, after)
    after.find("topform/bgbitmap/obj_encoded").text = "changed bitmap"
    assert not equivalent(before, after)


def test_explicit_null_attribute_roundtrip_and_removal(tmp_path: Path) -> None:
    from gorak.component_edits import overlay_metadata
    from gorak.parser import encode_w4gl

    folder = project(tmp_path)
    path = folder / "worker.w4gl"
    path.write_text(
        '[classsource]\nsuperclass="userobject"\n[attributes]\nrunner="GHOSTEXEC DEFAULT NULL"\nlookup="STRINGHASHTABLE"\n===\ninitialize={}\n'
    )
    node = decode_component(path)
    rows = {r.findtext("displayname"): r for r in node.findall("attributes/row")}
    assert rows["runner"].findtext("defaultvalue") == "2"
    assert rows["runner"].findtext("isnullable") == "1"
    assert rows["lookup"].find("defaultvalue") is None
    encoded = encode_w4gl(parse_component_node(node))
    assert 'runner = "GHOSTEXEC DEFAULT NULL"' in encoded
    path.write_text(encoded.replace("GHOSTEXEC DEFAULT NULL", "GHOSTEXEC"))
    overlay_metadata(node, path)
    assert node.find("attributes/row/defaultvalue") is None


def test_not_null_attribute_cannot_default_to_null(tmp_path: Path) -> None:
    folder = project(tmp_path)
    path = folder / "worker.w4gl"
    path.write_text(
        '[classsource]\nsuperclass="userobject"\n[attributes]\ncount="INTEGER NOT NULL DEFAULT NULL"\n===\ninitialize={}\n'
    )
    with pytest.raises(ProjectError, match="requires a nullable attribute"):
        decode_component(path)

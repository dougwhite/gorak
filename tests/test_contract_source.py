"""The established compact source remains directly importable without migration."""

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
    (tmp_path / "field_defaults.json").write_text("{}")
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
    assert field.find("bgcolor") is None
    assert field.findtext("xleft") == "500"
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


@pytest.mark.parametrize(
    ("attributes", "expected_gravity"),
    [
        ('xleft="500"', None),
        ('ytop="700"', None),
        ('xleft="100" ytop="200"', None),
        ('xleft="500" gravity="17"', "17"),
        ('ytop="700" gravity="19"', "19"),
        ("", None),
    ],
)
def test_compact_positioned_control_alignment_round_trip(
    tmp_path: Path, attributes: str, expected_gravity: str | None
) -> None:
    folder = project(tmp_path)
    path = folder / "panel.w4gl"
    path.write_text("[framesource]\n===\ninitialize()={}\n")
    path.with_suffix(".wml").write_text(
        '<frame><topform><subform name="container"><buttonfield '
        f'name="go" {attributes}/></subform></topform></frame>'
    )

    node = decode_component(path)
    control = node.find(".//childfields/row[name='go']")
    assert control is not None
    assert control.findtext("gravity") == expected_gravity
    coordinates = [control.findtext(key) for key in ("xleft", "ytop")]

    # Encoding must preserve intentional gravity even when it equals the
    # palette, and preserve positioning when coordinates equal the palette.
    markup = parse_component_node(node).markup
    assert markup is not None
    encoded = etree.fromstring(markup.encode()).find(".//buttonfield")
    assert encoded is not None
    assert encoded.get("gravity") == expected_gravity
    path.with_suffix(".wml").write_text(markup)
    again = decode_component(path).find(".//childfields/row[name='go']")
    assert again is not None
    assert again.findtext("gravity") == expected_gravity
    assert [again.findtext(key) for key in ("xleft", "ytop")] == coordinates


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


def test_removing_positioned_gravity_changes_existing_component(tmp_path: Path) -> None:
    folder = project(tmp_path)
    path = folder / "panel.w4gl"
    path.write_text("[framesource]\n===\ninitialize()={}\n")
    markup = '<frame><topform><buttonfield name="go" xleft="500" gravity="17"/></topform></frame>'
    path.with_suffix(".wml").write_text(markup)
    document = etree.Element("OPENROAD")
    document.append(decode_component(path))
    cache = tmp_path / ".openroad" / "example"
    cache.mkdir(parents=True)
    (cache / "panel.xml").write_bytes(etree.tostring(document))

    path.with_suffix(".wml").write_text(markup.replace(' gravity="17"', ""))
    node = comparison_component(path)
    control = node.find("topform/childfields/row")
    assert control is not None
    assert control.find("gravity") is None
    assert control.findtext("xleft") == "500"


def test_unknown_frame_property_is_refused(tmp_path: Path) -> None:
    folder = project(tmp_path)
    path = folder / "panel.w4gl"
    path.write_text("[framesource]\n===\ninitialize()={}")
    path.with_suffix(".wml").write_text(
        '<frame><topform><buttonfield invented="yes"/></topform></frame>'
    )
    with pytest.raises(ProjectError, match="Unsupported markup property"):
        decode_component(path)


def test_palette_selection_requires_explicit_selector(tmp_path: Path) -> None:
    folder = project(tmp_path)
    path = folder / "panel.w4gl"
    path.write_text("[framesource]\n===\ninitialize()={}")
    path.with_suffix(".wml").write_text(
        '<frame><topform><tablefield name="items" gorak_style="1" fgcolor="5"/></topform></frame>'
    )
    with pytest.raises(ProjectError, match="gorak_style"):
        decode_component(path)


def test_legacy_inline_queries_stay_out_of_w4gl(tmp_path: Path) -> None:
    from gorak.parser import encode_w4gl

    folder = project(tmp_path)
    path = folder / "item.w4gl"
    path.write_text(
        '[classsource]\nsuperclass="userobject"\nqueries=""\n===\ninitialize={}\n'
    )
    node = decode_component(path)
    assert node.find("queries") is None
    etree.SubElement(
        etree.SubElement(etree.SubElement(node, "queries"), "row"), "query"
    ).text = "unsupported designer data"
    etree.SubElement(node.find("queries"), "row_class").text = "queryobject"
    assert "queries" not in encode_w4gl(parse_component_node(node))


def test_explicit_bitmap_text_is_verified_exactly() -> None:
    from gorak.contract_source import equivalent

    source = '<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="panel" xsi:type="framesource"><topform><bgbitmap><obj_encoded>opaque line one\nline two</obj_encoded></bgbitmap></topform></COMPONENT>'
    before = etree.fromstring(source)
    after = etree.fromstring(source.replace("\n", " "))
    assert not equivalent(before, after)
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


@pytest.mark.parametrize(
    "kind", ["optionfield", "listfield", "radiofield", "palettefield"]
)
def test_exported_empty_structured_property_round_trips(kind: str) -> None:
    from gorak.contract_source import markup_node
    from gorak.parser import MarkupDefaultsIndex, frame_markup_element

    index = MarkupDefaultsIndex({}, {})
    original = etree.fromstring(
        f'<row xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="{kind}"><valuelist/></row>'
    )
    markup = frame_markup_element(original, index)
    assert markup.get("valuelist") == ""
    restored = markup_node(markup, "row", kind, index)
    assert restored.find("valuelist") is not None
    assert len(restored.find("valuelist")) == 0
    markup.set("valuelist", "not a structured value")
    with pytest.raises(ProjectError, match="Unsupported markup property"):
        markup_node(markup, "row", kind, index)

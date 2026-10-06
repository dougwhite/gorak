"""Canonical downstream inputs remain cache-free, reconstructible source."""

import json
import shutil
from pathlib import Path

from lxml import etree

from gorak.contract_source import equivalent
from gorak.export import application_metadata
from gorak.importer import signature
from gorak.native_styles import encode
from gorak.parser import parse_application_xml
from gorak.portable_source import restore_application, restore_component
from gorak.xml_text import text_value
from gorak.xml_writer import document
from tests.native_source import write_component

ROOT = Path(__file__).resolve().parents[1]


def test_compatibility_project_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    projected = tmp_path / "projected"
    shutil.copytree(ROOT / "compatibility/project", source)
    shutil.copytree(source, projected)
    paths = sorted(source.glob("*/*.w4gl"))
    assert len(paths) == 8
    for metadata in source.glob("*/app.json"):
        native = etree.fromstring(document([restore_application(metadata.parent)]))
        from gorak.image_assets import externalize

        native = externalize(
            native, projected / metadata.parent.name, metadata.parent.name
        )
        parsed = parse_application_xml(native)
        actual = application_metadata(
            parsed.application, included_applications=parsed.included_applications
        )
        expected = json.loads(metadata.read_text())
        assert actual == expected
    for path in paths:
        native = etree.fromstring(document([restore_component(path)])).find("COMPONENT")
        assert native is not None
        destination = projected / path.relative_to(source)
        # Re-export must generate the sidecar, not reuse the fixture copy.
        destination.with_suffix(".queries.json").unlink(missing_ok=True)
        write_component(destination, native)
        assert equivalent(native, restore_component(destination))
    assert (
        restore_component(source / "example/unstyled.w4gl").find("fielddefaults")
        is None
    )
    duplicates = restore_component(source / "example/duplicate_names.w4gl")
    children = duplicates.findall(".//row[name='child']")
    assert [c.findtext("textlabel") for c in children] == [
        "Nested",
        "Direct",
        "Sibling",
    ]
    assert "nested" in children[0].findtext("script")
    assert "direct" in children[1].findtext("script")
    typed = restore_component(source / "example/typed_values.w4gl")
    assert typed.findtext("attributes/row[displayname='amount_$T']/datatype") == "float"
    assert (
        typed.findtext("attributes/row[displayname='items']/datatype")
        == "shared!counter"
    )
    assert typed.findtext("attributes/row[displayname='items']/isarray") == "1"
    assert (
        typed.findtext("attributes/row[displayname='payload']/datatype") == "long byte"
    )
    assert typed.findtext("methods/row/datatype") == "shared!counter"
    library = restore_component(source / "example/automation.w4gl")
    assert library.findtext("uniqueid") == "{00020430-0000-0000-C000-000000000046}"
    assert library.findtext("minorversion") == "0"
    template = restore_component(source / "example/action.w4gl")
    assert (
        template.find("framefield").get(
            "{http://www.w3.org/2001/XMLSchema-instance}type"
        )
        == "buttonfield"
    )
    assert template.findtext("framefield/textlabel") == "Run"
    assert template.findtext("reportfield/textlabel") == "Report"
    panel = restore_component(source / "example/panel.w4gl")
    assert (
        panel.findtext("topform/childfields/row[name='quantity']/defaultvalue") == "1"
    )
    assert (
        panel.findtext("topform/childfields/row[name='nullable_default']/defaultvalue")
        == "2"
    )
    assert (
        panel.findtext("topform/childfields/row[name='specified_default']/defaultvalue")
        == "3"
    )
    assert (
        panel.findtext(
            "topform/childfields/row[name='specified_default']/defaultstring"
        )
        == "7"
    )
    projected_markup = etree.parse(str(projected / "example/panel.wml"))
    assert (
        projected_markup.find(".//entryfield[@name='quantity']").get("defaultvalue")
        is None
    )
    assert (
        projected_markup.find(".//entryfield[@name='nullable_default']").get(
            "defaultvalue"
        )
        == "2"
    )
    assert (
        projected_markup.find(".//entryfield[@name='specified_default']").get(
            "defaultvalue"
        )
        == "3"
    )
    assert panel.findtext("macro_vars/row/name") == "$CAPTION"
    assert panel.findtext("macro_vars/row/value") == "Preview"
    assert panel.findtext(".//cursor/syscursor") == "1"
    value = panel.find("topform/childfields/row/defaultstring")
    assert value is not None
    assert text_value(value) == "before\x07after"
    styles = panel.find("fielddefaults")
    assert styles is not None
    assert encode(styles)["groups"]["buttonfield"]["styles"]["style1"]["bgcolor"] == "8"
    button = panel.find("topform/childfields/row[name='calculate']")
    assert button is not None
    assert button.findtext("bgcolor") == "6"
    assert button.findtext("fieldstyle") == "1"
    assert "CALLPROC score" in (button.findtext("script") or "")
    assert (
        panel.find(".//protofield").get(
            "{http://www.w3.org/2001/XMLSchema-instance}type"
        )
        == "entryfield"
    )
    viewfield = panel.find(".//viewfield")
    assert viewfield is not None
    assert (
        viewfield.get("{http://www.w3.org/2001/XMLSchema-instance}type")
        == "flexibleform"
    )
    assert viewfield.findtext("ismovebounded") == "0"
    original = restore_component(source / "shared/counter.w4gl")
    queries = original.find("queries")
    assert queries is not None
    query = queries.find("row")
    assert query is not None
    assert query.findtext("name") == "load_counter"
    assert query.findtext("targetprefix") == "this."
    assert query.findtext("tables/row/tablename") == "counters"
    assert query.findtext("tables/row/corrname") == "c"
    assert query.findtext("designtimewhere") == "c.value >= 0"
    column = query.find("columns/row")
    assert column is not None
    assert column.findtext("columnname") == "value"
    assert column.findtext("fromtable_idx") == "1"
    assert column.findtext("datatypecode") == "30"
    assert column.findtext("datatypelength") == "4"
    assert column.findtext("datatypenullable") == "0"
    assert column.findtext("targets/row/expression") == "value"
    assert column.findtext("targets/row/isselecttarget") == "1"
    assert column.findtext("targets/row/useprefix") == "1"
    assert json.loads(
        (projected / "shared/counter.queries.json").read_text()
    ) == json.loads((source / "shared/counter.queries.json").read_text())
    restored = restore_component(projected / "shared/counter.w4gl")
    assert signature(queries) == signature(restored.find("queries"))


def test_image_contract_semantics(tmp_path: Path) -> None:
    from gorak.bitmap_codec import decode
    from gorak.image_assets import read_bitmap

    source = tmp_path / "project"
    shutil.copytree(ROOT / "compatibility/project", source)
    panel = restore_component(source / "example/panel.w4gl")
    expected = bytes(
        [230, 100, 30, 255, 130, 40, 200, 127, 30, 20, 10, 0, 30, 180, 240, 255]
    )
    for location in ("windowicon/obj_encoded", "topform/bgbitmap/obj_encoded"):
        assert decode(panel.findtext(location)).pixels == expected
    background = decode(panel.findtext("topform/bgbitmap/obj_encoded"))
    assert background.origin == "art/badge.png"
    assert background.tail[7:9] == ("1", "7")
    assert not list(source.rglob("*.bitmap.json"))
    assert not list(source.rglob("*.icons.json"))
    app = restore_application(source / "example")
    assert decode(app.findtext("windowicon/obj_encoded")).pixels == expected
    counter = restore_component(source / "shared/counter.w4gl")
    rows = counter.findall("extension/row")[1].findall("choiceitems/row")
    assert [row.findtext("enumvalue") for row in rows] == ["1", "2", "3"]
    pixels = read_bitmap(source / "shared", "images/counter.png").pixels
    assert decode(rows[0].findtext("enumbitmap/obj_encoded")).pixels == pixels
    other = read_bitmap(source / "shared", "images/counter-active.png").pixels
    assert other != pixels
    restored = decode(rows[1].findtext("enumbitmap/obj_encoded"))
    assert restored.pixels == other
    assert restored.mask == b"\x80\x40"
    assert restored.header[12] == "12"


def test_builtin_fixture_needs_no_local_copy(tmp_path: Path) -> None:
    from gorak.bitmap_codec import decode
    from gorak.image_assets import read_bitmap

    source = tmp_path / "project"
    shutil.copytree(ROOT / "compatibility/project", source)
    counter = restore_component(source / "shared/counter.w4gl")
    rows = counter.findall("extension/row")[1].findall("choiceitems/row")
    assert decode(rows[2].findtext("enumbitmap/obj_encoded")) == read_bitmap(
        source / "shared", "builtin:class-icon-16"
    )
    assert not (source / "shared/images/class-icon-16.png").exists()

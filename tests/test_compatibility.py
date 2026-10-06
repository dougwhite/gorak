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
    assert len(paths) == 3
    for metadata in source.glob("*/app.json"):
        native = etree.fromstring(document([restore_application(metadata.parent)]))
        parsed = parse_application_xml(native)
        assert application_metadata(
            parsed.application, included_applications=parsed.included_applications
        ) == json.loads(metadata.read_text())
    for path in paths:
        native = etree.fromstring(document([restore_component(path)])).find("COMPONENT")
        assert native is not None
        destination = projected / path.relative_to(source)
        # Re-export must generate the sidecar, not reuse the fixture copy.
        destination.with_suffix(".queries.json").unlink(missing_ok=True)
        write_component(destination, native)
        assert equivalent(native, restore_component(destination))
    panel = restore_component(source / "example/panel.w4gl")
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

"""Canonical downstream inputs remain cache-free, reconstructible source."""

import json
import shutil
import tomllib
from pathlib import Path

from lxml import etree

from gorak.contract_source import equivalent
from gorak.export import application_metadata
from gorak.native_styles import encode
from gorak.parser import parse_application_xml
from gorak.portable_source import restore_application, restore_component
from gorak.xml_text import text_value
from gorak.xml_writer import document
from tests.native_source import write_component

ROOT = Path(__file__).resolve().parents[1]


def test_dependency_map_references_real_contracts_and_components() -> None:
    manifest = tomllib.loads((ROOT / "ecosystem.toml").read_text())
    assert manifest["canonical_repository"] == "dougwhite/gorak"
    assert (ROOT / manifest["fixtures"]).is_dir()
    contracts = manifest["contracts"]
    components = manifest["components"]
    assert len(components) == 5
    for contract in contracts.values():
        assert contract["version"] >= 1
        assert (ROOT / contract["documentation"]).is_file()
    for component in components.values():
        assert set(component["consumes"]) <= contracts.keys()
        assert set(component["bundles"]) <= components.keys()
        assert set(component.get("planned_bundles", [])) <= components.keys()
    for interface in manifest["interfaces"].values():
        assert interface["producer"] in components
        assert set(interface["consumers"]) <= components.keys()
    for asset in manifest["assets"].values():
        assert asset["contract"] in contracts
        assert asset["producer"] in components
        assert asset["consumer"] in components


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

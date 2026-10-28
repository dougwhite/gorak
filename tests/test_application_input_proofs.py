"""Application context and component dependencies use verified source bytes."""

import json
from pathlib import Path

import pytest
from lxml import etree
from PIL import Image

from gorak import sync_plan
from gorak.connection import OpenRoadConnection
from gorak.domain import Application
from gorak.portable_source import comparison_application, comparison_component
from gorak.xml_writer import document, new_application


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("changed", ["metadata", "image"])
def test_application_context_cannot_hide_transient_metadata_or_image_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warm: bool, changed: str
) -> None:
    folder = tmp_path / "Example"
    folder.mkdir()
    manifest = folder / "app.json"
    metadata: dict[str, object] = {"description": "Database description"}
    if changed == "image":
        images = folder / "images"
        images.mkdir()
        target = images / "icon.png"
        Image.new("RGB", (2, 2), "red").save(target)
        metadata["window_icon"] = "images/icon.png"
    else:
        target = manifest
    manifest.write_text(json.dumps(metadata))
    native = new_application(folder)
    etree.SubElement(native, "commandline").text = "-native-context"
    xml = document([native])
    original = target.read_bytes()
    if changed == "image":
        Image.new("RGB", (2, 2), "blue").save(target)
    else:
        metadata["description"] = "Pending local description"
        manifest.write_text(json.dumps(metadata))
    pending = target.read_bytes()
    if warm:
        sync_plan.local_inventory(tmp_path)
    monkeypatch.setattr(
        sync_plan, "read_applications", lambda _: [Application("Example", "", "")]
    )
    monkeypatch.setattr(
        sync_plan, "backup_application_xml", lambda c, a, p: p.write_bytes(xml)
    )
    contexts: list[bool] = []

    def racing(
        path: Path, *, native_context: etree._Element | None = None
    ) -> etree._Element:
        if native_context is None:
            return comparison_application(path)
        contexts.append(True)
        target.write_bytes(original)
        try:
            return comparison_application(path, native_context=native_context)
        finally:
            target.write_bytes(pending)

    monkeypatch.setattr(sync_plan, "comparison_application", racing)
    connection = OpenRoadConnection("local", "node", "db", None)
    plan = sync_plan.plan_project(connection, tmp_path)
    assert contexts == [True]
    assert plan == [sync_plan.Change("example", "conflict", "added", "added")]
    assert target.read_bytes() == pending
    assert not list((tmp_path / ".openroad").glob("*/*.xml"))
    monkeypatch.setattr(sync_plan, "comparison_application", comparison_application)
    assert sync_plan.plan_project(connection, tmp_path) == plan


def test_transient_query_sidecar_edit_cannot_poison_component_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_query_metadata import component, source

    path = source(tmp_path, component())
    sidecar = path.with_suffix(".queries.json")
    original = sidecar.read_bytes()
    pending = original.replace(b'"main"', b'"pending_local_query"')
    assert pending != original
    sidecar.write_bytes(pending)

    def racing(path: Path) -> etree._Element:
        sidecar.write_bytes(original)
        try:
            return comparison_component(path)
        finally:
            sidecar.write_bytes(pending)

    monkeypatch.setattr(sync_plan, "comparison_component", racing)
    baseline, _, disk, invalid = sync_plan.local_inventory(tmp_path)
    assert (
        "example/sample" in invalid
        or baseline["example/sample"] != disk["example/sample"]
    )
    assert sidecar.read_bytes() == pending
    monkeypatch.setattr(sync_plan, "comparison_component", comparison_component)
    baseline, _, disk, invalid = sync_plan.local_inventory(tmp_path)
    assert not invalid
    assert baseline["example/sample"] != disk["example/sample"]


def test_transient_shared_stylesheet_edit_cannot_poison_frame_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import native_styles
    from gorak.xml_writer import new_component
    from tests.native_source import write_component
    from tests.test_query_metadata import component

    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    path = folder / "sample.w4gl"
    frame = component("framesource")
    empty_styles = frame.find("fielddefaults")
    assert empty_styles is not None
    frame.replace(empty_styles, native_styles.decode(native_styles.baseline()))
    write_component(path, frame)
    baseline_path = tmp_path / ".openroad/example/example.xml"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_bytes(document([new_application(folder), new_component(path)]))
    stylesheet = tmp_path / "field_defaults.json"
    original = stylesheet.read_bytes()
    stylesheet.write_text(
        json.dumps({"groups": {"entryfield": {"styles": {"style1": {"width": "321"}}}}})
    )
    pending = stylesheet.read_bytes()

    def racing(path: Path) -> etree._Element:
        stylesheet.write_bytes(original)
        try:
            return comparison_component(path)
        finally:
            stylesheet.write_bytes(pending)

    monkeypatch.setattr(sync_plan, "comparison_component", racing)
    baseline, _, disk, invalid = sync_plan.local_inventory(tmp_path)
    assert (
        "example/sample" in invalid
        or baseline["example/sample"] != disk["example/sample"]
    )
    assert stylesheet.read_bytes() == pending
    monkeypatch.setattr(sync_plan, "comparison_component", comparison_component)
    baseline, _, disk, invalid = sync_plan.local_inventory(tmp_path)
    assert not invalid
    assert baseline["example/sample"] != disk["example/sample"]

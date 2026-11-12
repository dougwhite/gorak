"""Fresh application comparisons preserve native details without a baseline."""

import json
from collections.abc import Generator
from pathlib import Path

import pytest
from lxml import etree

from gorak import sync_plan
from gorak.connection import OpenRoadConnection
from gorak.domain import Application
from gorak.portable_source import comparison_application
from gorak.xml_writer import document, new_application


def application(root: Path, variant: str = "unrepresented") -> etree._Element:
    folder = root / "Example"
    folder.mkdir()
    (folder / "app.json").write_text(
        json.dumps({"description": "Original", "included_applications": ["helper"]})
    )
    node = new_application(folder)
    if variant == "unrepresented":
        etree.SubElement(node, "commandline").text = "-launch"
        etree.SubElement(node, "globalsfile").text = "native.glb"
    else:
        includes = node.find("included_apps")
        assert includes is not None
        core = includes.find("row")
        assert core is not None
        image = core.find("imgfilename")
        assert image is not None
        core.remove(image)
        etree.SubElement(core, "sequence").text = "9"
        includes.remove(core)
        includes.insert(1, core)
    return node


def connection(
    monkeypatch: pytest.MonkeyPatch, native: etree._Element
) -> OpenRoadConnection:
    xml = document([native])
    monkeypatch.setattr(
        sync_plan, "read_applications", lambda _: [Application("Example", "", "")]
    )
    monkeypatch.setattr(
        sync_plan, "backup_application_xml", lambda c, a, p: p.write_bytes(xml)
    )
    return OpenRoadConnection("local", "node", "db", None)


@pytest.mark.parametrize("variant", ["unrepresented", "include_representation"])
def test_fresh_application_uses_context_without_creating_a_historical_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    native = application(tmp_path, variant)
    current = connection(monkeypatch, native)
    before = sync_plan.local_inventory(tmp_path)
    standalone = sync_plan.semantic_hashes(before[2])
    assert not before[0]
    assert standalone["example"] != sync_plan.signature(native)
    source = (tmp_path / "Example/app.json").read_bytes()

    changes = sync_plan.plan_project(current, tmp_path)

    assert changes == [sync_plan.Change("example", "converged", "added", "added")]
    assert not list((tmp_path / ".openroad").glob("*/*.xml"))
    assert (tmp_path / "Example/app.json").read_bytes() == source
    after = sync_plan.local_inventory(tmp_path)
    assert not after[0]
    # A plan's temporary context must not replace standalone source evidence.
    assert sync_plan.semantic_hashes(after[2]) == standalone


@pytest.mark.parametrize(
    "edit",
    [
        {"description": "Local edit"},
        {"starting_component": "local_start"},
        {"included_applications": ["different"]},
    ],
)
def test_fresh_application_context_does_not_hide_managed_local_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, edit: dict[str, object]
) -> None:
    native = application(tmp_path)
    current = connection(monkeypatch, native)
    source = tmp_path / "Example/app.json"
    metadata = json.loads(source.read_text())
    metadata.update(edit)
    source.write_text(json.dumps(metadata))

    changes = sync_plan.plan_project(current, tmp_path)

    assert changes == [sync_plan.Change("example", "conflict", "added", "added")]
    assert not list((tmp_path / ".openroad").glob("*/*.xml"))


def test_historical_application_metadata_difference_stays_a_pull(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = application(tmp_path)
    baseline = tmp_path / ".openroad/Example/Example.xml"
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(document([native]))
    original = baseline.read_bytes()
    commandline = native.find("commandline")
    assert commandline is not None
    commandline.text = "-changed-in-database"

    changes = sync_plan.plan_project(connection(monkeypatch, native), tmp_path)

    assert changes == [sync_plan.Change("example", "pull", "unchanged", "modified")]
    assert baseline.read_bytes() == original


def test_unsupported_native_context_keeps_managed_local_edit_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = application(tmp_path)
    etree.SubElement(native, "unknown_native_detail").text = "preserve"
    current = connection(monkeypatch, native)
    source = tmp_path / "Example/app.json"
    metadata = json.loads(source.read_text())
    metadata["description"] = "Local edit"
    source.write_text(json.dumps(metadata))

    changes = sync_plan.plan_project(current, tmp_path)

    assert changes == [sync_plan.Change("example", "conflict", "added", "added")]
    assert not list((tmp_path / ".openroad").glob("*/*.xml"))


def test_native_context_stream_closes_without_populating_the_baseline_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = application(tmp_path)
    current = connection(monkeypatch, native)
    closed: list[bool] = []

    def stream(path: Path) -> Generator[etree._Element, None, None]:
        try:
            yield etree.fromstring(etree.tostring(native))
            raise AssertionError("Context comparison needs only the application node")
        finally:
            closed.append(True)

    def indexed(*args: object) -> etree._Element:
        raise AssertionError("Temporary exports must not enter the baseline index")

    monkeypatch.setattr(sync_plan, "application_children", stream)
    monkeypatch.setattr(sync_plan, "cached_node_at", indexed)

    changes = sync_plan.plan_project(current, tmp_path)

    assert changes == [sync_plan.Change("example", "converged", "added", "added")]
    assert closed == [True]


@pytest.mark.parametrize("historical", [False, True])
def test_application_context_is_independent_and_never_overrides_history(
    tmp_path: Path, historical: bool
) -> None:
    native = application(tmp_path)
    folder = tmp_path / "Example"
    if historical:
        baseline = tmp_path / ".openroad/Example/Example.xml"
        baseline.parent.mkdir(parents=True)
        baseline.write_bytes(document([native]))
    commandline = native.find("commandline")
    assert commandline is not None
    commandline.text = "-current-context"
    original = etree.tostring(native)
    metadata = json.loads((folder / "app.json").read_text())
    metadata["description"] = "Local edit"
    (folder / "app.json").write_text(json.dumps(metadata))

    result = comparison_application(folder, native_context=native)

    assert result.findtext("versshortremarks") == "Local edit"
    assert result.findtext("commandline") == (
        "-launch" if historical else "-current-context"
    )
    assert etree.tostring(native) == original
    result.clear()
    assert etree.tostring(native) == original

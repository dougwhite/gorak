"""Persist comparison results only for the exact bytes reconstruction consumed."""

import os
from contextlib import nullcontext
from pathlib import Path

import pytest
from lxml import etree

from gorak import comparison_cache, source_xml, sync_plan
from gorak.portable_source import (
    cached_source_scope,
    read_document,
)
from gorak.project import ProjectError
from tests.test_sync_plan import setup, xml


def test_native_inventory_digest_describes_bytes_actually_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".openroad/example/example.xml"
    path.parent.mkdir(parents=True)
    original = xml().encode()
    path.write_bytes(original)
    expected = sync_plan.xml_inventory(read_document(path), "example")

    def racing(path: Path, *, data: bytes | None = None) -> etree._Element:
        path.write_bytes(original.replace(b"RETURN 1;", b"RETURN 2;"))
        try:
            return read_document(path, data=data)
        finally:
            path.write_bytes(original)

    monkeypatch.setattr(sync_plan, "read_document", racing)
    with comparison_cache.project_scope(tmp_path):
        first = sync_plan.path_inventory(path, "example", str(tmp_path))
    with comparison_cache.project_scope(tmp_path):
        second = sync_plan.path_inventory(path, "example", str(tmp_path))
    assert first == second == expected


@pytest.mark.parametrize(
    "relative",
    [
        "field_defaults.json",
        "example/field_defaults.json",
        "example/proc.queries.json",
        "example/proc.icons.json",
        "example/images/icon.png.bitmap.json",
    ],
)
def test_non_file_dependencies_cannot_disappear_from_comparison_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    setup(tmp_path, monkeypatch, xml())
    sync_plan.local_inventory(tmp_path)
    invalid = tmp_path / relative
    invalid.mkdir(parents=True)
    with pytest.raises(ProjectError, match="not a regular file"):
        sync_plan.local_inventory(tmp_path)


def test_native_snapshot_read_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source_xml, "MAX_DOCUMENT_BYTES", 8)
    path = tmp_path / "oversized.xml"
    path.write_bytes(b"x" * 20)
    with pytest.raises(ProjectError, match="document limit"):
        comparison_cache.read_xml_bytes(path)


def test_warm_inventory_rechecks_source_after_reading_persistent_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup(tmp_path, monkeypatch, xml())
    sync_plan.local_inventory(tmp_path)
    source = tmp_path / "example/proc.w4gl"
    original = source.read_bytes()
    pending = original.replace(b"RETURN 1;", b"RETURN 2;")
    source.write_bytes(pending)
    read_digest = comparison_cache.file_digest
    raced = False

    def racing(path: Path) -> str:
        nonlocal raced
        if path != source or raced:
            return read_digest(path)
        raced = True
        source.write_bytes(original)
        try:
            return read_digest(path)
        finally:
            source.write_bytes(pending)

    monkeypatch.setattr(comparison_cache, "file_digest", racing)
    with pytest.raises(ProjectError, match="Local source changed"):
        sync_plan.local_inventory(tmp_path)
    assert source.read_bytes() == pending


@pytest.mark.parametrize("kind", ["full", "overlap", "disjoint"])
def test_equal_baseline_times_require_unambiguous_overlay_order(
    tmp_path: Path, kind: str
) -> None:
    folder = tmp_path / ".openroad/example"
    folder.mkdir(parents=True)
    first = folder / "first.xml"
    first.write_text(
        '<OPENROAD><APPLICATION name="example"/></OPENROAD>'
        if kind == "full"
        else '<OPENROAD><COMPONENT name="first"><script>RETURN 1;</script></COMPONENT></OPENROAD>'
    )
    second = folder / "second.xml"
    name = "second" if kind == "disjoint" else "first"
    second.write_text(
        f'<OPENROAD><COMPONENT name="{name}"><script>RETURN 2;</script></COMPONENT></OPENROAD>'
    )
    for path in (first, second):
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    if kind == "disjoint":
        inventory, _ = sync_plan.baseline_inventory(tmp_path)
        assert set(inventory) == {"example/first", "example/second"}
    else:
        with pytest.raises(ProjectError, match="Baseline export order is ambiguous"):
            sync_plan.baseline_inventory(tmp_path)


@pytest.mark.parametrize("kind", ["partial-partial", "full-partial", "full-full"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("deferred", [False, True])
def test_equal_baseline_times_accept_order_independent_overlaps(
    tmp_path: Path, kind: str, reverse: bool, deferred: bool
) -> None:
    folder = tmp_path / ".openroad/example"
    folder.mkdir(parents=True)
    application = '<APPLICATION name="example"/>'
    component = '<COMPONENT name="proc"><script>RETURN 1;</script></COMPONENT>'
    # Different raw XML still has the same accepted native meaning.
    equivalent = component.replace("RETURN 1;", "\nRETURN 1;\n")
    documents = [
        (application if kind.startswith("full") else "") + component,
        (application if kind.endswith("full") else "") + equivalent,
    ]
    if reverse:
        documents.reverse()
    for index, content in enumerate(documents):
        path = folder / f"{index}.xml"
        path.write_text(f"<OPENROAD>{content}</OPENROAD>")
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    with (
        comparison_cache.scope() if deferred else nullcontext(),
        cached_source_scope(),
    ):
        inventory, _ = sync_plan.baseline_inventory(tmp_path)
        assert set(inventory) == (
            {"example/proc"}
            if kind == "partial-partial"
            else {"example", "example/proc"}
        )


@pytest.mark.parametrize("partial_name", ["a.xml", "z.xml"])
def test_equal_baseline_times_bind_the_same_raw_component_during_reconstruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial_name: str
) -> None:
    setup(tmp_path, monkeypatch, xml())
    full = tmp_path / ".openroad/example/example.xml"
    partial = full.with_name(partial_name)
    document = etree.fromstring(xml("\nRETURN 1;\n").encode())
    application = document.find("APPLICATION")
    assert application is not None
    document.remove(application)
    partial.write_bytes(etree.tostring(document))
    for path in (full, partial):
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    for _ in range(2):
        baseline, _, disk, invalid = sync_plan.local_inventory(tmp_path)
        assert not invalid
        assert baseline["example/proc"] == disk["example/proc"]

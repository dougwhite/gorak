"""Comparison inventories retain the readable membership of their byte proof."""

import os
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from gorak import comparison_cache, sync_plan
from gorak.portable_source import comparison_application
from gorak.project import ProjectError
from gorak.xml_writer import document, new_application, new_component


@pytest.mark.parametrize("missing", ["component", "manifest", "application"])
def test_temporary_source_disappearance_cannot_persist_a_false_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    root = tmp_path / "project"
    folder = root / "example"
    folder.mkdir(parents=True)
    manifest = folder / "app.json"
    manifest.write_text("{}")
    source = folder / "proc.w4gl"
    source.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    baseline = root / ".openroad/example/example.xml"
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(document([new_application(folder), new_component(source)]))
    target = source if missing == "component" else manifest
    original_bytes = target.read_bytes()
    detached = tmp_path / "detached"
    expected_keys = {"example", "example/proc"}
    initial_key = comparison_cache.project_key(root)
    original_key = comparison_cache.project_key
    original_application = comparison_application
    original_inventory = sync_plan.baseline_inventory
    key_calls = 0
    removed = False

    def remove_input() -> None:
        nonlocal removed
        removed = True
        if missing == "application":
            folder.rename(detached)
        else:
            target.unlink()

    def restoring_key(*args: Any, **kwargs: Any) -> str:
        nonlocal key_calls
        key_calls += 1
        if key_calls == 2:
            assert removed
            if missing == "application":
                detached.rename(folder)
            else:
                target.write_bytes(original_bytes)
        return original_key(*args, **kwargs)

    def application_then_remove(*args: Any, **kwargs: Any) -> etree._Element:
        result = original_application(*args, **kwargs)
        remove_input()
        return result

    def inventory_then_remove(
        *args: Any, **kwargs: Any
    ) -> tuple[dict[str, object], set[str]]:
        result = original_inventory(*args, **kwargs)
        remove_input()
        return result

    with monkeypatch.context() as race:
        race.setattr(comparison_cache, "project_key", restoring_key)
        if missing == "component":
            race.setattr(sync_plan, "comparison_application", application_then_remove)
        else:
            race.setattr(sync_plan, "baseline_inventory", inventory_then_remove)
        _, _, disk, invalid = sync_plan.local_inventory(root)

    assert key_calls == 2
    assert target.read_bytes() == original_bytes
    assert original_key(root) == initial_key
    assert ("example/proc" if missing == "component" else "example") in invalid
    assert set(disk) | set(invalid) == expected_keys
    with comparison_cache.project_scope(root):
        assert (
            comparison_cache.load("local:" + str(root.resolve()), initial_key) is None
        )

    # A separate command must see the restored source, rather than reuse an
    # inventory that certified its temporary omission as a component deletion.
    native, _, disk, invalid = sync_plan.local_inventory(root)
    assert not invalid
    assert set(disk) == expected_keys
    assert native == disk


def baseline_project(root: Path) -> tuple[Path, Path, Path]:
    folder = root / "example"
    folder.mkdir(parents=True)
    (folder / "app.json").write_text("{}")
    source = folder / "proc.w4gl"
    source.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    baseline = root / ".openroad/example/example.xml"
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(document([new_application(folder), new_component(source)]))
    overlay = baseline.with_name("proc.xml")
    node = new_component(source)
    node.find("script").text = "RETURN 2;"
    overlay.write_bytes(document([node]))
    os.utime(baseline, ns=(1_000_000_000, 1_000_000_000))
    os.utime(overlay, ns=(2_000_000_000, 2_000_000_000))
    return folder, baseline, overlay


@pytest.mark.parametrize("missing", ["full", "component"])
def test_temporary_baseline_disappearance_refuses_incomplete_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _, baseline, overlay = baseline_project(tmp_path)
    target = baseline if missing == "full" else overlay
    original_bytes = target.read_bytes()
    original_stat = target.stat()
    original_key = comparison_cache.project_key
    key_calls = 0

    def restore() -> None:
        target.write_bytes(original_bytes)
        os.utime(target, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    def key_then_remove(*args: Any, **kwargs: Any) -> str:
        nonlocal key_calls
        key_calls += 1
        if key_calls > 1:
            restore()
        result = original_key(*args, **kwargs)
        if key_calls == 1:
            target.unlink()
        return result

    try:
        with monkeypatch.context() as race:
            race.setattr(comparison_cache, "project_key", key_then_remove)
            with pytest.raises(ProjectError, match="Native XML changed"):
                sync_plan.local_inventory(tmp_path)
    finally:
        restore()
    assert not comparison_cache.storage_path(tmp_path).exists()
    native, _, disk, invalid = sync_plan.local_inventory(tmp_path)
    assert not invalid
    assert set(native) == set(disk) == {"example", "example/proc"}
    assert native["example/proc"] != disk["example/proc"]


def test_baseline_overlay_order_uses_the_initial_project_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, baseline, _ = baseline_project(tmp_path)
    original_stat = baseline.stat()
    original_inventory = sync_plan.baseline_inventory
    original_key = comparison_cache.project_key(tmp_path)

    def temporarily_reordered(
        *args: Any, **kwargs: Any
    ) -> tuple[dict[str, object], set[str]]:
        os.utime(baseline, ns=(3_000_000_000, 3_000_000_000))
        try:
            return original_inventory(*args, **kwargs)
        finally:
            os.utime(
                baseline,
                ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
            )

    with monkeypatch.context() as race:
        race.setattr(sync_plan, "baseline_inventory", temporarily_reordered)
        native, _, disk, invalid = sync_plan.local_inventory(tmp_path)
    assert not invalid
    assert comparison_cache.project_key(tmp_path) == original_key
    assert native["example/proc"] != disk["example/proc"]
    # The persisted result must agree with the actual restored overlay order.
    again, _, current, invalid = sync_plan.local_inventory(tmp_path)
    assert not invalid
    assert again == native and current == disk


def test_tracking_inventory_must_consume_the_initially_hashed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline_project(tmp_path)
    tracking = tmp_path / ".openroad/tracked-applications.json"
    tracking.write_bytes(b'["example"]')
    original_bytes = tracking.read_bytes()
    original_read = Path.read_bytes

    def changed_read(path: Path) -> bytes:
        if path != tracking:
            return original_read(path)
        tracking.write_bytes(b'["unexpected"]')
        try:
            return original_read(path)
        finally:
            tracking.write_bytes(original_bytes)

    with monkeypatch.context() as race:
        race.setattr(Path, "read_bytes", changed_read)
        with pytest.raises(ProjectError, match="Tracked application inventory changed"):
            sync_plan.local_inventory(tmp_path)
    assert tracking.read_bytes() == original_bytes
    assert not comparison_cache.storage_path(tmp_path).exists()
    _, apps, _, invalid = sync_plan.local_inventory(tmp_path)
    assert not invalid and apps == {"example"}

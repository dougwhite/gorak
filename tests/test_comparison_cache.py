import os
from pathlib import Path

import pytest
from lxml import etree

from gorak import comparison_cache, sync_plan


@pytest.fixture(autouse=True)
def cache_location(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GORAK_COMPARISON_CACHE_DIR", str(tmp_path / "cache"))


def test_key_detects_same_size_same_mtime_edits_and_dependency_changes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source = root / "source.wml"
    source.write_text("one")
    stamp = source.stat()
    first = comparison_cache.project_key(root)
    source.write_text("two")
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert comparison_cache.project_key(root) != first
    previous = comparison_cache.project_key(root)
    for name in ("field_defaults.json", "images/icon.png", ".openroad/app/app.xml"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"one")
        assert comparison_cache.project_key(root) != previous
        previous = comparison_cache.project_key(root)
        path.write_bytes(b"two")
        assert comparison_cache.project_key(root) != previous
        previous = comparison_cache.project_key(root)
    source.unlink()
    assert comparison_cache.project_key(root) != previous


def test_invalid_cache_and_unwritable_cache_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    comparison_cache.save("scope", "key", {"inventory": {"component": "a" * 64}})
    assert comparison_cache.load("scope", "key") is not None
    path = comparison_cache.cache_path("scope", "key")
    path.write_text('{"payload": {}, "sha256":"wrong"}')
    assert comparison_cache.load("scope", "key") is None
    path.write_text("not JSON")
    assert comparison_cache.load("scope", "key") is None
    blocked = tmp_path / "blocked"
    blocked.write_text("file, not directory")
    monkeypatch.setenv("GORAK_COMPARISON_CACHE_DIR", str(blocked))
    comparison_cache.save("scope", "key", {})
    assert comparison_cache.load("scope", "key") is None


def test_xml_cache_preserves_hashes_and_rechecks_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "app.xml"
    path.write_text(
        '<OPENROAD><COMPONENT name="proc"><script>one</script></COMPONENT></OPENROAD>'
    )
    expected = sync_plan.xml_inventory(etree.parse(path).getroot(), "app")
    first = sync_plan.path_inventory(path, "app", "test")
    assert first == expected
    from gorak.portable_source import read_document

    original = read_document

    def forbidden(path: Path) -> etree._Element:
        raise AssertionError("Unchanged XML must not be reparsed")

    monkeypatch.setattr(sync_plan, "read_document", forbidden)
    second = sync_plan.path_inventory(path, "app", "test")
    assert second == first
    assert sync_plan.semantic_hashes(second) == sync_plan.semantic_hashes(first)
    monkeypatch.setattr(sync_plan, "read_document", original)
    path.write_text(path.read_text().replace("one", "two"))
    assert sync_plan.path_inventory(path, "app", "test") != first


def test_local_cache_invalidates_source_and_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    folder = root / "example"
    folder.mkdir(parents=True)
    (folder / "app.json").write_text("{}")
    source = folder / "proc.w4gl"
    source.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    other = folder / "other.w4gl"
    other.write_text(source.read_text())
    first = sync_plan.local_inventory(root)
    assert not first[3]
    from gorak.portable_source import comparison_component

    original = comparison_component
    calls: list[Path] = []

    def component(path: Path) -> etree._Element:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(sync_plan, "comparison_component", component)
    second = sync_plan.local_inventory(root)
    assert first == second
    assert sync_plan.semantic_hashes(first[2]) == sync_plan.semantic_hashes(second[2])
    assert calls == []
    # Unrelated edits do not reconstruct components; shared image edits do.
    (root / "notes.txt").write_text("human notes")
    sync_plan.local_inventory(root)
    assert calls == []
    image = folder / "images" / "unused.png"
    image.parent.mkdir()
    image.write_bytes(b"dependency added")
    sync_plan.local_inventory(root)
    assert calls == [other, source]
    stamp = source.stat()
    source.write_text(source.read_text().replace("RETURN 1", "RETURN 2"))
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    third = sync_plan.local_inventory(root)
    assert third[2] != second[2]
    assert calls == [other, source, source]


def test_changes_during_reconstruction_are_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    folder = root / "example"
    folder.mkdir(parents=True)
    (folder / "app.json").write_text("{}")
    source = folder / "proc.w4gl"
    source.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    key = comparison_cache.project_key(root)
    from gorak.portable_source import comparison_component

    original = comparison_component

    def changing(path: Path) -> etree._Element:
        result = original(path)
        path.write_text(path.read_text().replace("RETURN 1", "RETURN 2"))
        return result

    monkeypatch.setattr(sync_plan, "comparison_component", changing)
    sync_plan.local_inventory(root)
    assert comparison_cache.load("local:" + str(root.resolve()), key) is None


def test_baseline_timestamp_precedence_invalidates_inventory(tmp_path: Path) -> None:
    root = tmp_path / "project"
    baseline = root / ".openroad" / "example" / "example.xml"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("<OPENROAD/>")
    first = comparison_cache.project_key(root)
    stamp = baseline.stat()
    os.utime(baseline, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1000000000))
    assert comparison_cache.project_key(root) != first


def test_valid_cache_hits_refresh_eviction_age() -> None:
    comparison_cache.save("scope", "key", {"inventory": {}})
    path = comparison_cache.cache_path("scope", "key")
    os.utime(path, ns=(1, 1))
    assert comparison_cache.load("scope", "key") is not None
    assert path.stat().st_mtime_ns > 1


def test_symlink_image_cannot_reuse_regular_image_cache(tmp_path: Path) -> None:
    root = tmp_path / "project"
    folder = root / "example"
    image = folder / "images" / "icon.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image contents")
    target = tmp_path / "outside.png"
    target.write_bytes(image.read_bytes())
    first = comparison_cache.project_key(root)
    shared = comparison_cache.shared_key(root, folder)
    image.unlink()
    try:
        image.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    assert comparison_cache.project_key(root) != first
    assert comparison_cache.shared_key(root, folder) != shared


def test_cache_entry_is_bound_to_its_input_and_scope() -> None:
    comparison_cache.save("first", "one", {"inventory": {}})
    original = comparison_cache.cache_path("first", "one")
    other = comparison_cache.cache_path("second", "two")
    other.write_bytes(original.read_bytes())
    assert comparison_cache.load("second", "two") is None


def test_changed_xml_only_normalizes_changed_subtree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "app.xml"
    path.write_text(
        '<OPENROAD><APPLICATION name="app"/><COMPONENT name="first"><script>one</script></COMPONENT><COMPONENT name="second"><script>two</script></COMPONENT></OPENROAD>'
    )
    sync_plan.path_inventory(path, "app", "scope")
    path.write_text(path.read_text().replace("two", "changed"))
    expected = sync_plan.xml_inventory(etree.parse(path).getroot(), "app")
    original = sync_plan.signature
    calls: list[str | None] = []

    def normalizing(node: etree._Element) -> sync_plan.SemanticDigest:
        calls.append(node.get("name"))
        return original(node)

    monkeypatch.setattr(sync_plan, "signature", normalizing)
    assert sync_plan.path_inventory(path, "app", "scope") == expected
    assert calls == ["second"]


def test_changed_baseline_only_reconstructs_affected_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.portable_source import (
        comparison_component,
        restore_application,
        restore_component,
    )
    from gorak.xml_writer import document

    root = tmp_path / "project"
    folder = root / "example"
    folder.mkdir(parents=True)
    (folder / "app.json").write_text("{}")
    first = folder / "first.w4gl"
    second = folder / "second.w4gl"
    for path, number in ((first, 1), (second, 2)):
        path.write_text(f'[proc4glsource]\ndatatype="integer"\n===\nRETURN {number};')
    baseline = root / ".openroad" / "example" / "example.xml"
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(
        document(
            [
                restore_application(folder),
                restore_component(first),
                restore_component(second),
            ]
        )
    )
    sync_plan.local_inventory(root)
    calls: list[Path] = []

    def reconstructing(path: Path) -> etree._Element:
        calls.append(path)
        return comparison_component(path)

    monkeypatch.setattr(sync_plan, "comparison_component", reconstructing)
    baseline.write_bytes(baseline.read_bytes().replace(b"RETURN 2;", b"RETURN 3;"))
    incremental = sync_plan.local_inventory(root)
    assert calls == [second]
    blocked = tmp_path / "disabled"
    blocked.write_text("not a directory")
    monkeypatch.setenv("GORAK_COMPARISON_CACHE_DIR", str(blocked))
    assert sync_plan.local_inventory(root) == incremental
    assert calls == [second, first, second]


def test_invalid_source_does_not_prevent_reuse_of_valid_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.portable_source import comparison_component

    root = tmp_path / "project"
    folder = root / "example"
    folder.mkdir(parents=True)
    (folder / "app.json").write_text("{}")
    valid = folder / "valid.w4gl"
    valid.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    invalid = folder / "invalid.w4gl"
    invalid.write_text("invalid source")
    first = sync_plan.local_inventory(root)
    assert "example/invalid" in first[3]
    calls: list[Path] = []

    def reconstructing(path: Path) -> etree._Element:
        calls.append(path)
        return comparison_component(path)

    monkeypatch.setattr(sync_plan, "comparison_component", reconstructing)
    assert sync_plan.local_inventory(root) == first
    assert calls == [invalid]

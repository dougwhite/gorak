import os
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from lxml import etree

from gorak import comparison_cache, sync_plan


@pytest.fixture(autouse=True)
def comparison_scope() -> Iterator[None]:
    with comparison_cache.scope():
        yield


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


def test_reused_results_are_independent_and_bound_to_scope_and_input() -> None:
    comparison_cache.save("first", "one", {"inventory": {"component": "a" * 64}})
    result = comparison_cache.load("first", "one")
    assert result is not None
    result.clear()
    assert comparison_cache.load("first", "one") == {
        "inventory": {"component": "a" * 64}
    }
    assert comparison_cache.load("second", "one") is None
    assert comparison_cache.load("first", "two") is None


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


def test_xml_that_changes_during_read_is_refused_before_returning_an_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.portable_source import read_document
    from gorak.project import ProjectError

    path = tmp_path / "app.xml"
    path.write_text(
        '<OPENROAD><COMPONENT name="proc"><script>one</script></COMPONENT></OPENROAD>'
    )
    initial_key = comparison_cache.file_digest(path)
    original = read_document

    def changing(source: Path) -> etree._Element:
        result = original(source)
        source.write_bytes(source.read_bytes().replace(b"one", b"two"))
        return result

    monkeypatch.setattr(sync_plan, "read_document", changing)
    with pytest.raises(ProjectError, match="Native XML changed during comparison"):
        sync_plan.path_inventory(path, "app", "test")
    assert comparison_cache.load("xml:test:app", initial_key) is None
    assert comparison_cache.load("native-components:test:app", "latest") is None


@pytest.mark.parametrize("memo_kind", ["components", "xml"])
def test_transient_native_read_cannot_prime_a_persisted_false_source_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, memo_kind: str
) -> None:
    from gorak import safe_pull
    from gorak.portable_source import read_document
    from gorak.source_xml import from_bytes
    from gorak.xml_writer import document, new_application, new_component

    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    source = folder / "proc.w4gl"
    source.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    initial = document([new_application(folder), new_component(source)])
    transient = initial.replace(b"RETURN 1;", b"RETURN 2;")
    snapshot = safe_pull.fingerprint(tmp_path)
    path = tmp_path / ".openroad/example/example.xml"
    path.parent.mkdir(parents=True)
    path.write_bytes(initial)
    stamp = path.stat()
    plan = [
        sync_plan.Change("example", "converged", "added", "added"),
        sync_plan.Change("example/proc", "converged", "added", "added"),
    ]
    original_read = read_document
    original_inventory = sync_plan.baseline_inventory
    original_load = comparison_cache.load

    def restore() -> None:
        path.write_bytes(initial)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    def restoring(source: Path) -> etree._Element:
        result = original_read(source)
        if source == path:
            restore()
        return result

    def changing(*args: Any, **kwargs: Any) -> tuple[dict[str, object], set[str]]:
        path.write_bytes(transient)
        try:
            return original_inventory(*args, **kwargs)
        finally:
            restore()

    def loading(scope: str, key: str) -> dict[str, object] | None:
        result = original_load(scope, key)
        if scope.startswith("xml:"):
            restore()
        return result

    token = comparison_cache._entries.set(None)
    try:
        with comparison_cache.project_scope(tmp_path):
            # Previously normalized component memos have no deferred-file
            # binding, so that independent check cannot catch this race.
            if memo_kind == "components":
                memo: dict[str, object] = {}
                sync_plan.xml_inventory(
                    from_bytes(transient), "example", next_memo=memo
                )
                comparison_cache.save(
                    "native-components:" + str(tmp_path.resolve()) + ":example",
                    "latest",
                    {"entries": memo},
                )
            else:
                path.write_bytes(transient)
                sync_plan.path_inventory(path, "example", str(tmp_path.resolve()))
                restore()
            with monkeypatch.context() as race:
                race.setattr(sync_plan, "read_document", restoring)
                race.setattr(safe_pull, "baseline_inventory", changing)
                if memo_kind == "xml":
                    race.setattr(comparison_cache, "load", loading)
                assert not safe_pull.prime_matching_baseline(
                    tmp_path, snapshot, {path: initial}, plan
                )
        expected = sync_plan.xml_inventory(from_bytes(initial), "example")
        baseline, _, disk, invalid = sync_plan.local_inventory(tmp_path)
        assert not invalid
        assert baseline == disk == expected
        assert path.read_bytes() == initial
    finally:
        comparison_cache._entries.reset(token)


def test_verified_baseline_inventory_rejects_unexpected_xml_paths(
    tmp_path: Path,
) -> None:
    from gorak.project import ProjectError

    path = tmp_path / ".openroad/example/example.xml"
    path.parent.mkdir(parents=True)
    path.write_text('<OPENROAD><APPLICATION name="example"/></OPENROAD>')
    expected = {
        path.relative_to(tmp_path).as_posix(): comparison_cache.file_digest(path)
    }
    (path.parent / "later.xml").write_bytes(path.read_bytes())

    with pytest.raises(ProjectError, match="Native XML changed during comparison"):
        sync_plan.baseline_inventory(tmp_path, expected_digests=expected)


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


@pytest.mark.parametrize("changed", ["source", "image"])
def test_transient_key_bytes_cannot_hide_a_later_edit_in_persisted_memos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    from io import BytesIO

    from PIL import Image

    from gorak.xml_writer import document, new_application, new_component

    folder = tmp_path / "example"
    folder.mkdir()
    manifest = folder / "app.json"
    manifest.write_text("{}")
    module: ModuleType
    if changed == "source":
        source = folder / "proc.w4gl"
        original_bytes = b'[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;'
        edited_bytes = original_bytes.replace(b"RETURN 1", b"RETURN 2")
        source.write_bytes(original_bytes)
        nodes = [new_application(folder), new_component(source)]
        target_key = "example/proc"
        module = sync_plan
        helper = "source_input_key"
    else:
        source = folder / "images/icon.png"
        source.parent.mkdir()
        images = []
        for color in ("red", "blue"):
            output = BytesIO()
            Image.new("RGB", (1, 1), color).save(output, format="PNG")
            images.append(output.getvalue())
        original_bytes, edited_bytes = images
        source.write_bytes(original_bytes)
        manifest.write_text('{"window_icon":{"src":"images/icon.png"}}')
        nodes = [new_application(folder)]
        target_key = "example"
        module = comparison_cache
        helper = "shared_key"
    baseline = tmp_path / ".openroad/example/example.xml"
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(document(nodes))
    original: Callable[..., str] = getattr(module, helper)

    def transient(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("verified_digests") is not None or (
            changed == "source" and args[1] != source
        ):
            return original(*args, **kwargs)
        source.write_bytes(edited_bytes)
        try:
            return original(*args, **kwargs)
        finally:
            source.write_bytes(original_bytes)

    # Exercise separate commands loading the actual persisted JSON metadata.
    token = comparison_cache._entries.set(None)
    try:
        monkeypatch.setattr(module, helper, transient)
        native, _, disk, invalid = sync_plan.local_inventory(tmp_path)
        assert not invalid
        assert native[target_key] == disk[target_key]
        assert comparison_cache.storage_path(tmp_path).exists()
        monkeypatch.setattr(module, helper, original)
        source.write_bytes(edited_bytes)

        native, _, disk, invalid = sync_plan.local_inventory(tmp_path)

        assert not invalid
        assert native[target_key] != disk[target_key]
    finally:
        comparison_cache._entries.reset(token)


def test_baseline_timestamp_precedence_invalidates_inventory(tmp_path: Path) -> None:
    root = tmp_path / "project"
    baseline = root / ".openroad" / "example" / "example.xml"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("<OPENROAD/>")
    first = comparison_cache.project_key(root)
    stamp = baseline.stat()
    os.utime(baseline, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1000000000))
    assert comparison_cache.project_key(root) != first


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

    def normalizing(node: etree._Element) -> object:
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
    monkeypatch.setattr(comparison_cache, "load", lambda *args: None)
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


def test_operation_scope_releases_results_and_never_writes_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Clear the fixture's outer scope to exercise independent command lifetimes.
    token = comparison_cache._entries.set(None)
    try:
        monkeypatch.setenv("GORAK_COMPARISON_CACHE_DIR", str(tmp_path / "forbidden"))
        with comparison_cache.scope():
            comparison_cache.save("one", "two", {"value": "result"})
            comparison_cache.remember_semantic("raw", "digest")
            with comparison_cache.scope():
                assert comparison_cache.load("one", "two") == {"value": "result"}
                assert comparison_cache.semantic("raw") == "digest"
        with comparison_cache.scope():
            assert comparison_cache.load("one", "two") is None
            assert comparison_cache.semantic("raw") is None
        assert not list(tmp_path.iterdir())
    finally:
        comparison_cache._entries.reset(token)


def test_identical_component_bytes_skip_repeated_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = etree.fromstring(b'<COMPONENT name="proc"><script>body</script></COMPONENT>')
    first = sync_plan.signature(node)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("Identical bytes must reuse semantic comparison")

    monkeypatch.setattr(sync_plan, "native_signature", forbidden)
    assert sync_plan.signature(etree.fromstring(etree.tostring(node))) == first

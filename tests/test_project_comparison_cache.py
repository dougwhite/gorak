"""Persistent comparison metadata is disposable, byte-bound and bounded."""

import json
import os
import sys
from pathlib import Path

import pytest
from lxml import etree

from gorak import comparison_cache as cache
from gorak import sync_plan
from gorak.portable_source import (
    comparison_application,
    comparison_component,
    read_document,
)
from gorak.xml_writer import document


def deferred(root: Path, script: str = "RETURN 1;") -> sync_plan.DeferredDigest:
    path = root / ".openroad/example/example.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<OPENROAD><COMPONENT name="calculate"><script>'
        + script
        + "</script></COMPONENT></OPENROAD>"
    )
    cache.file_digest(path)
    node = read_document(path).find("COMPONENT")
    assert node is not None
    value = sync_plan.DeferredDigest(
        sync_plan.raw_hash(node), path, "COMPONENT", "calculate"
    )
    cache.remember_semantic(value.raw, value)
    return value


def test_metadata_roundtrip_is_lazy_independent_and_not_written_mid_operation(
    tmp_path: Path,
) -> None:
    path = cache.storage_path(tmp_path)
    with cache.project_scope(tmp_path):
        value = deferred(tmp_path)
        cache.save("local", "input", {"inventory": {"example/calculate": value}})
        assert not path.exists()
        assert value.digest is None
    assert path.exists()
    assert b"RETURN" not in path.read_bytes()
    original = path.read_bytes()
    with cache.project_scope(tmp_path):
        result = cache.load("local", "input")
        assert result is not None
        inventory = result["inventory"]
        assert isinstance(inventory, dict)
        restored = inventory["example/calculate"]
        assert isinstance(restored, sync_plan.DeferredDigest)
        assert restored.digest is None
        assert sync_plan.semantic_hash(restored) == sync_plan.semantic_hash(value)
        inventory.clear()
        assert cache.load("local", "input") != result
        assert cache.load("local", "other") is None
        assert cache.load("other", "input") is None
    # A read-only warm hit does not rewrite identical metadata.
    assert path.read_bytes() == original


def test_default_scope_has_no_persistent_storage(tmp_path: Path) -> None:
    with cache.scope():
        cache.save("scope", "input", {"value": "one"})
    with cache.scope():
        assert cache.load("scope", "input") is None
    assert not cache.storage_path(tmp_path).exists()


@pytest.mark.parametrize("corruption", ["truncated", "checksum", "implementation"])
def test_corrupt_or_incompatible_metadata_is_only_a_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    with cache.project_scope(tmp_path):
        cache.save("scope", "input", {"value": sync_plan.SemanticDigest("a" * 64)})
    path = cache.storage_path(tmp_path)
    if corruption == "truncated":
        path.write_bytes(b'{"data":')
    elif corruption == "checksum":
        path.write_bytes(path.read_bytes().replace(b"a" * 64, b"b" * 64))
    else:
        monkeypatch.setattr(cache, "implementation_key", lambda: "different")
    with cache.project_scope(tmp_path):
        assert cache.load("scope", "input") is None
        cache.save("scope", "new", {"value": "recomputed"})
    with cache.project_scope(tmp_path):
        assert cache.load("scope", "new") == {"value": "recomputed"}


def test_stale_baseline_references_are_misses_even_when_size_and_mtime_match(
    tmp_path: Path,
) -> None:
    with cache.project_scope(tmp_path):
        value = deferred(tmp_path)
        cache.save("native", "latest", {"signature": value})
    path = value.path
    stat = path.stat()
    path.write_bytes(path.read_bytes().replace(b"RETURN 1;", b"RETURN 2;"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with cache.project_scope(tmp_path):
        assert cache.load("native", "latest") is None


def test_new_baseline_generation_is_persisted_but_stale_refs_are_not(
    tmp_path: Path,
) -> None:
    with cache.project_scope(tmp_path):
        before = deferred(tmp_path)
        cache.save("old", "input", {"signature": before})
        after = deferred(tmp_path, "RETURN 2;")
        cache.save("new", "input", {"signature": after})
    with cache.project_scope(tmp_path):
        assert cache.load("old", "input") is None
        result = cache.load("new", "input")
        assert result is not None
        assert result["signature"] == after


def test_resolved_hashes_remain_reusable_without_original_xml(tmp_path: Path) -> None:
    with cache.project_scope(tmp_path):
        value = deferred(tmp_path)
        expected = sync_plan.semantic_hash(value)
        cache.save("native", "input", {"signature": value})
    value.path.unlink()
    with cache.project_scope(tmp_path):
        result = cache.load("native", "input")
        assert result == {"signature": sync_plan.SemanticDigest(expected)}


def test_failed_atomic_publication_preserves_old_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with cache.project_scope(tmp_path):
        cache.save("scope", "input", {"value": "old"})
    target = cache.storage_path(tmp_path)
    before = target.read_bytes()
    original = Path.replace

    def denied(path: Path, destination: Path | str) -> Path:
        if path.name.startswith(".comparison-cache-"):
            assert target.read_bytes() == before
            raise PermissionError("read only")
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", denied)
    with cache.project_scope(tmp_path):
        cache.save("scope", "input", {"value": "new"})
    assert target.read_bytes() == before
    assert not list(target.parent.glob(".comparison-cache-*.tmp"))


def test_failed_operation_does_not_publish_metadata(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), cache.project_scope(tmp_path):
        cache.save("scope", "input", {"value": "unfinished"})
        raise RuntimeError("stop")
    assert not cache.storage_path(tmp_path).exists()


def test_cache_size_and_entry_count_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache, "MAX_CACHE_BYTES", 4096)
    monkeypatch.setattr(cache, "MAX_ENTRY_BYTES", 1024)
    monkeypatch.setattr(cache, "MAX_ENTRIES", 3)
    with cache.project_scope(tmp_path):
        cache.save("scope", "huge", {"value": "x" * 2000})
        cache.save("scope", "small", {"value": "usable"})
    path = cache.storage_path(tmp_path)
    assert path.stat().st_size <= 4096
    with cache.project_scope(tmp_path):
        assert cache.load("scope", "huge") is None
        assert cache.load("scope", "small") == {"value": "usable"}
        for index in range(10):
            cache.save("scope", str(index), {"value": index})
    document = json.loads(path.read_bytes())
    assert len(document["data"]["entries"]) <= 3
    assert path.stat().st_size <= 4096


def test_project_binding_and_override_do_not_write_source_project(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    metadata = tmp_path / "separate" / "cache.json"
    with cache.project_scope(root, cache_path=metadata):
        cache.save("scope", "input", {"value": "one"})
    assert metadata.exists()
    assert not cache.storage_path(root).exists()
    other = tmp_path / "other"
    other.mkdir()
    with cache.project_scope(other, cache_path=metadata):
        assert cache.load("scope", "input") is None


def test_project_decorator_finds_positional_and_keyword_roots(tmp_path: Path) -> None:
    @cache.project_cached
    def operation(connection: object, root: Path, *, number: int) -> int:
        cache.save("scope", "input", {"value": number})
        return number

    assert operation(None, tmp_path, number=1) == 1
    assert operation(None, root=tmp_path, number=2) == 2
    with cache.project_scope(tmp_path):
        assert cache.load("scope", "input") == {"value": 2}


@pytest.mark.parametrize("nested", [".git", ".openroad"])
def test_nested_image_directories_participate_in_project_content_key(
    tmp_path: Path, nested: str
) -> None:
    asset = tmp_path / "example/images" / nested / "icon.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"one")
    before = cache.project_key(tmp_path)
    asset.write_bytes(b"two")
    assert cache.project_key(tmp_path) != before


def test_persisted_local_inventory_rechecks_input_bytes_before_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    source = folder / "calculate.w4gl"
    source.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    first = sync_plan.local_inventory(tmp_path)
    assert not first[3]
    original = comparison_component
    calls: list[Path] = []

    def comparing(path: Path) -> object:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(sync_plan, "comparison_component", comparing)
    assert sync_plan.local_inventory(tmp_path) == first
    assert not calls
    stat = source.stat()
    source.write_text(source.read_text().replace("RETURN 1;", "RETURN 2;"))
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = sync_plan.local_inventory(tmp_path)
    assert changed[2] != first[2]
    assert calls == [source]


def test_changed_baseline_only_reconstructs_its_source_in_next_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    sources = [folder / "first.w4gl", folder / "second.w4gl"]
    for source in sources:
        source.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    baseline = tmp_path / ".openroad/example/example.xml"
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(
        document(
            [comparison_application(folder)]
            + [comparison_component(source) for source in sources]
        )
    )
    first = sync_plan.local_inventory(tmp_path)
    assert not first[3]
    assert all(
        isinstance(first[2]["example/" + source.stem], sync_plan.DeferredDigest)
        for source in sources
    )
    tree = read_document(baseline)
    script = tree.find("COMPONENT[@name='first']/script")
    assert script is not None
    script.text = "RETURN 2;"
    baseline.write_bytes(etree.tostring(tree))
    calls: list[Path] = []

    def comparing(path: Path) -> etree._Element:
        calls.append(path)
        return comparison_component(path)

    monkeypatch.setattr(sync_plan, "comparison_component", comparing)
    # local_inventory owns its scope, so this command reloads persisted metadata.
    changed = sync_plan.local_inventory(tmp_path)
    assert not changed[3]
    assert calls == [sources[0]]
    assert set(changed[2]) == {"example", "example/first", "example/second"}
    assert changed[0]["example/first"] != changed[2]["example/first"]
    assert changed[0]["example/second"] == changed[2]["example/second"]


@pytest.mark.parametrize("scope", ["components:example", "local:example"])
def test_only_independent_component_records_can_be_partially_loaded(
    tmp_path: Path, scope: str
) -> None:
    with cache.project_scope(tmp_path):
        value = deferred(tmp_path)
        cache.save(
            scope,
            "input",
            {
                "stale.w4gl": {"signature": value},
                "valid.w4gl": {"signature": sync_plan.SemanticDigest("b" * 64)},
            },
        )
    value.path.unlink()
    with cache.project_scope(tmp_path):
        result = cache.load(scope, "input")
        assert result == (
            {"valid.w4gl": {"signature": sync_plan.SemanticDigest("b" * 64)}}
            if scope.startswith("components:")
            else None
        )


def test_unchanged_subtree_can_rebind_to_freshly_verified_file_generation(
    tmp_path: Path,
) -> None:
    with cache.project_scope(tmp_path):
        original = deferred(tmp_path)
        cache.save("native", "input", {"signature": original})
    original.path.write_bytes(
        original.path.read_bytes().replace(
            b"</OPENROAD>", b'<COMPONENT name="new"/></OPENROAD>'
        )
    )
    with cache.project_scope(tmp_path):
        cache.file_digest(original.path)
        node = read_document(original.path).find("COMPONENT")
        assert node is not None
        observed = sync_plan.DeferredDigest(
            sync_plan.raw_hash(node), original.path, "COMPONENT", "calculate"
        )
        cache.remember_semantic(observed.raw, observed)
        result = cache.load("native", "input")
        assert result is not None
        assert sync_plan.semantic_hash(result["signature"]) == sync_plan.semantic_hash(
            observed
        )


def test_external_deferred_reference_is_not_persisted(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    external = tmp_path / "outside.xml"
    external.write_text('<OPENROAD><COMPONENT name="calculate"/></OPENROAD>')
    with cache.project_scope(root):
        cache.file_digest(external)
        value = sync_plan.DeferredDigest("a" * 64, external, "COMPONENT", "calculate")
        cache.save("native", "input", {"signature": value})
    with cache.project_scope(root):
        assert cache.load("native", "input") is None


def test_implementation_identity_changes_when_packaged_source_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    source = package / "comparison.py"
    source.write_text("def compare(): return 1\n")
    with monkeypatch.context() as patch:
        patch.setattr(cache, "__file__", str(package / "comparison_cache.py"))
        cache.implementation_key.cache_clear()
        first = cache.implementation_key()
        source.write_text("def compare(): return 2\n")
        cache.implementation_key.cache_clear()
        assert cache.implementation_key() != first
    cache.implementation_key.cache_clear()


def test_frozen_implementation_identity_includes_executable_with_templates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "package"
    template = package / "templates" / "shape.json"
    template.parent.mkdir(parents=True)
    template.write_text("{}")
    executable = tmp_path / "program.exe"
    executable.write_bytes(b"first executable")
    with monkeypatch.context() as patch:
        patch.setattr(cache, "__file__", str(package / "comparison_cache.py"))
        patch.setattr(sys, "frozen", True, raising=False)
        patch.setattr(sys, "executable", str(executable))
        cache.implementation_key.cache_clear()
        first = cache.implementation_key()
        executable.write_bytes(b"second executable")
        cache.implementation_key.cache_clear()
        assert cache.implementation_key() != first
    cache.implementation_key.cache_clear()

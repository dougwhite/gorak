"""Byte-first comparisons retain exact native/checkpoint fallback behavior."""

import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from lxml import etree

from gorak import comparison_cache, portable_source, sync_plan, windows_file_info
from gorak.native_normalization import signature as native_signature
from gorak.portable_source import cached_source_scope, read_document
from gorak.project import ProjectError


def document(script: str = "RETURN 1;") -> str:
    return (
        '<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:unused="urn:unused"><APPLICATION name="example"/>'
        '<COMPONENT name="calculate" xsi:type="proc4glsource">'
        f"<script>{script}</script><datatype>integer</datatype>"
        "</COMPONENT></OPENROAD>"
    )


def baseline_file(root: Path, content: str | None = None) -> Path:
    path = root / ".openroad/example/example.xml"
    path.parent.mkdir(parents=True)
    path.write_text(document() if content is None else content, encoding="utf-8")
    return path


def reference(path: Path) -> dict[str, str]:
    return {
        (
            "example"
            if node.tag == "APPLICATION"
            else "example/" + node.get("name", "").casefold()
        ): sync_plan.semantic_hash(native_signature(node, pixel_geometry=True))
        for node in read_document(path)
    }


def test_equal_native_bytes_do_not_require_semantic_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = baseline_file(tmp_path)
    current = tmp_path / "current.xml"
    current.write_bytes(path.read_bytes())

    def unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("Equal native bytes need no normalization")

    monkeypatch.setattr(sync_plan, "native_signature", unexpected)
    with comparison_cache.scope():
        baseline, _ = sync_plan.baseline_inventory(tmp_path)
        assert all(
            isinstance(value, sync_plan.DeferredDigest) for value in baseline.values()
        )
        database = sync_plan.path_inventory(current, "example", str(tmp_path.resolve()))
        assert baseline == database
        assert all(
            sync_plan.compare(key, value, value, database[key]).action == "unchanged"
            for key, value in baseline.items()
        )


def test_deferred_checkpoints_preserve_hashes_and_unused_namespaces(
    tmp_path: Path,
) -> None:
    path = baseline_file(tmp_path)
    expected = reference(path)
    before = path.read_bytes()
    with comparison_cache.scope():
        values, _ = sync_plan.baseline_inventory(tmp_path)
    # The owning comparison scope has ended before checkpoint materialization.
    assert sync_plan.semantic_hashes(values) == expected
    assert sync_plan.semantic_hashes(values) == expected
    assert path.read_bytes() == before


def test_adopted_baseline_rebinds_reused_native_hashes(tmp_path: Path) -> None:
    old = baseline_file(tmp_path)
    expected = reference(old)
    adopted = old.with_name("adopted.xml")
    with comparison_cache.scope(), cached_source_scope():
        sync_plan.path_inventory(old, "example", str(tmp_path), defer_path=old)
        adopted.write_bytes(old.read_bytes())
        old.unlink()
        values = sync_plan.path_inventory(
            adopted, "example", str(tmp_path), defer_path=adopted
        )
        assert sync_plan.semantic_hashes(values) == expected
        assert all(
            isinstance(value, sync_plan.DeferredDigest) and value.path == adopted
            for value in values.values()
        )


def test_different_xml_bytes_use_legacy_equivalence_in_both_directions(
    tmp_path: Path,
) -> None:
    path = baseline_file(tmp_path, document("  RETURN 1;\n"))
    baseline, _ = sync_plan.baseline_inventory(tmp_path)
    node = read_document(path).find("COMPONENT")
    assert node is not None
    node.find("script").text = "RETURN 1;"
    actual = sync_plan.signature(node)
    expected = baseline["example/calculate"]
    assert expected == actual
    assert actual == expected
    assert not expected != actual
    assert sync_plan.semantic_hash(expected) == sync_plan.semantic_hash(actual)
    node.find("script").text = "RETURN 2;"
    different = sync_plan.signature(node)
    assert expected != different
    assert different != expected


def test_newer_component_baseline_is_resolved_from_its_exact_file(
    tmp_path: Path,
) -> None:
    original = baseline_file(tmp_path)
    newer = original.with_name("calculate.xml")
    newer.write_text(document("RETURN 2;").replace('<APPLICATION name="example"/>', ""))
    os.utime(original, ns=(1_000, 1_000))
    os.utime(newer, ns=(2_000, 2_000))
    values, _ = sync_plan.baseline_inventory(tmp_path)
    expected = reference(original) | reference(newer)
    assert sync_plan.semantic_hashes(values) == expected
    assert (
        sync_plan.semantic_hash(values["example/calculate"])
        != reference(original)["example/calculate"]
    )


def test_newer_complete_export_records_component_absence(tmp_path: Path) -> None:
    complete = baseline_file(tmp_path)
    old = complete.with_name("calculate.xml")
    old.write_bytes(
        complete.read_bytes().replace(b'<APPLICATION name="example"/>', b"")
    )
    complete.write_text('<OPENROAD><APPLICATION name="example"/></OPENROAD>')
    os.utime(old, ns=(1_000, 1_000))
    os.utime(complete, ns=(2_000, 2_000))
    values, apps = sync_plan.baseline_inventory(tmp_path)
    assert apps == {"example"}
    assert set(values) == {"example"}
    assert sync_plan.semantic_hashes(values) == reference(complete)


def test_database_results_survive_temporary_export_removal(tmp_path: Path) -> None:
    path = baseline_file(tmp_path)
    current = tmp_path / "current.xml"
    current.write_text(document("RETURN 2;"))
    expected = reference(current)
    with comparison_cache.scope():
        sync_plan.baseline_inventory(tmp_path)
        database = sync_plan.path_inventory(current, "example", str(tmp_path.resolve()))
        current.unlink()
        assert sync_plan.semantic_hashes(database) == expected
    assert path.exists()


def test_deferred_resolution_rejects_same_size_same_mtime_baseline_edit(
    tmp_path: Path,
) -> None:
    path = baseline_file(tmp_path)
    original_time = path.stat().st_mtime_ns
    with comparison_cache.scope(), cached_source_scope():
        values, _ = sync_plan.baseline_inventory(tmp_path)
        # Materialize only the application so the XML index is already populated.
        sync_plan.semantic_hash(values["example"])
        path.write_bytes(path.read_bytes().replace(b"RETURN 1;", b"RETURN 2;"))
        os.utime(path, ns=(original_time, original_time))
        with pytest.raises(ProjectError, match="Baseline changed"):
            sync_plan.semantic_hash(values["example/calculate"])


def test_deferred_resolution_uses_windows_change_time_with_unchanged_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = baseline_file(tmp_path)
    original = path.stat()
    real_stat = Path.stat
    generation = [1]

    def windows_stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        current = real_stat(self, follow_symlinks=follow_symlinks)
        if self != path:
            return current
        fields = {
            key: getattr(current, key) for key in dir(current) if key.startswith("st_")
        }
        fields["st_ctime_ns"] = original.st_ctime_ns
        return cast(os.stat_result, SimpleNamespace(**fields))

    monkeypatch.setattr(Path, "stat", windows_stat)
    monkeypatch.setattr(portable_source, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(windows_file_info, "change_time", lambda path: generation[0])
    with comparison_cache.scope(), cached_source_scope():
        values, _ = sync_plan.baseline_inventory(tmp_path)
        sync_plan.semantic_hash(values["example"])
        path.write_bytes(path.read_bytes().replace(b"RETURN 1;", b"RETURN 2;"))
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        generation[0] += 1
        current = path.stat()
        assert (current.st_mtime_ns, current.st_ctime_ns, current.st_size) == (
            original.st_mtime_ns,
            original.st_ctime_ns,
            original.st_size,
        )
        with pytest.raises(ProjectError, match="Baseline changed"):
            sync_plan.semantic_hash(values["example/calculate"])


def test_windows_metadata_errors_do_not_reuse_cached_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = baseline_file(tmp_path)
    monkeypatch.setattr(portable_source, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(windows_file_info, "change_time", lambda path: 1)

    def unavailable(path: Path) -> int:
        raise OSError("metadata query failed")

    with comparison_cache.scope(), cached_source_scope():
        values, _ = sync_plan.baseline_inventory(tmp_path)
        sync_plan.semantic_hash(values["example"])
        monkeypatch.setattr(windows_file_info, "change_time", unavailable)
        with pytest.raises(ProjectError, match="Baseline changed"):
            sync_plan.semantic_hash(values["example/calculate"])
    assert path.exists()


def test_windows_unchanged_baseline_reuses_one_parsed_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = baseline_file(tmp_path)
    reads: list[Path] = []

    def counted_read(path: Path) -> etree._Element:
        reads.append(path)
        return read_document(path)

    monkeypatch.setattr(portable_source, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(windows_file_info, "change_time", lambda path: 1)
    monkeypatch.setattr(portable_source, "read_document", counted_read)
    with cached_source_scope():
        for _ in range(10):
            assert (
                portable_source.cached_node_at(path, "APPLICATION", "example")
                is not None
            )
            assert (
                portable_source.cached_node_at(path, "COMPONENT", "calculate")
                is not None
            )
    assert reads == [path]


def test_deferred_resolution_rejects_disappeared_baseline(tmp_path: Path) -> None:
    path = baseline_file(tmp_path)
    with comparison_cache.scope():
        values, _ = sync_plan.baseline_inventory(tmp_path)
    path.unlink()
    with pytest.raises(ProjectError, match="Baseline changed"):
        sync_plan.semantic_hash(values["example/calculate"])


def test_direct_baseline_snapshot_survives_later_file_replacement(
    tmp_path: Path,
) -> None:
    path = baseline_file(tmp_path)
    expected = reference(path)
    values, _ = sync_plan.baseline_inventory(tmp_path)
    path.write_text(document("RETURN 2;"))
    assert sync_plan.semantic_hashes(values) == expected
    assert all(isinstance(value, sync_plan.SemanticDigest) for value in values.values())


@pytest.mark.parametrize(
    "content",
    [
        '<frmflow><row oidref="missing"/></frmflow>',
        "<script><?unsupported value?></script>",
        "<script><structured>unsupported</structured></script>",
        "<values><row/><row_class><?unsupported value?></row_class></values>",
        "<defaultvalue><?unsupported value?></defaultvalue>",
        '<row xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:type="rectangleshape"><width><?unsupported value?></width></row>',
    ],
)
def test_deferred_inventory_preserves_rejected_native_layouts(
    tmp_path: Path, content: str
) -> None:
    path = baseline_file(
        tmp_path,
        '<OPENROAD><COMPONENT name="calculate">' + content + "</COMPONENT></OPENROAD>",
    )
    node = read_document(path).find("COMPONENT")
    assert node is not None
    with pytest.raises(ProjectError):
        native_signature(node, pixel_geometry=True)
    with comparison_cache.scope(), pytest.raises(ProjectError):
        sync_plan.baseline_inventory(tmp_path)


def test_semantic_checkpoint_database_values_match_deferred_local_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_sync_plan import setup, xml

    connection = setup(tmp_path, monkeypatch, xml())
    baseline = tmp_path / ".openroad/example/example.xml"
    hashes = {
        (
            "example"
            if node.tag == "APPLICATION"
            else "example/" + node.get("name", "")
        ): sync_plan.semantic_hash(native_signature(node, pixel_geometry=True))
        for node in read_document(baseline)
    }
    changes = sync_plan.plan_project(connection, tmp_path, database_hashes=hashes)
    assert all(change.action == "unchanged" for change in changes)


def test_deferred_hash_keeps_special_xml_node_kinds(tmp_path: Path) -> None:
    path = baseline_file(
        tmp_path,
        '<OPENROAD><COMPONENT name="calculate"><!--comment-->'
        "<?test value?><extension>literal</extension></COMPONENT></OPENROAD>",
    )
    values, _ = sync_plan.baseline_inventory(tmp_path)
    assert sync_plan.semantic_hashes(values) == reference(path)
    # Verbatim XML equality must not flatten comments/PIs into element text.
    other = etree.fromstring(
        '<COMPONENT name="calculate"><comment>comment</comment>'
        "<?test value?><extension>literal</extension></COMPONENT>"
    )
    assert values["example/calculate"] != sync_plan.signature(other)


def test_source_memos_rebind_when_identical_baseline_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = baseline_file(tmp_path, document().replace(' xmlns:unused="urn:unused"', ""))
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    (folder / "calculate.w4gl").write_text(
        '[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;'
    )
    expected = reference(path)

    def unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("Identical source should reuse its comparison")

    with comparison_cache.scope():
        first = sync_plan.local_inventory(tmp_path)
        assert isinstance(first[2]["example/calculate"], sync_plan.DeferredDigest)
        path.rename(path.with_name("new-export.xml"))
        monkeypatch.setattr(sync_plan, "comparison_application", unexpected)
        monkeypatch.setattr(sync_plan, "comparison_component", unexpected)
        baseline, _, disk, invalid = sync_plan.local_inventory(tmp_path)
        assert not invalid
        assert sync_plan.semantic_hashes(baseline) == expected
        assert sync_plan.semantic_hashes(disk) == expected
        changed = etree.fromstring(
            '<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'name="calculate" xsi:type="proc4glsource">'
            "<script>RETURN 2;</script><datatype>integer</datatype></COMPONENT>"
        )
        assert (
            sync_plan.compare(
                "example/calculate",
                baseline["example/calculate"],
                disk["example/calculate"],
                sync_plan.signature(changed),
            ).action
            == "pull"
        )


def test_source_memo_without_current_native_locator_reconstructs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.portable_source import comparison_component

    path = baseline_file(tmp_path, document().replace(' xmlns:unused="urn:unused"', ""))
    source = tmp_path / "example" / "calculate.w4gl"
    source.parent.mkdir()
    source.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    node = read_document(path).find("COMPONENT")
    assert node is not None
    raw = sync_plan.raw_hash(node)
    with comparison_cache.scope():
        comparison_cache.remember_semantic(
            raw, sync_plan.DeferredDigest(raw, path, "COMPONENT", "calculate")
        )
        records: dict[str, object] = {}
        sync_plan.compare_source(
            tmp_path, source.parent, source, {}, records, baseline_raw=raw
        )
        comparison_cache._semantics.set({})
        calls: list[Path] = []

        def reconstructing(path: Path) -> etree._Element:
            calls.append(path)
            return comparison_component(path)

        monkeypatch.setattr(sync_plan, "comparison_component", reconstructing)
        result = sync_plan.compare_source(
            tmp_path, source.parent, source, records, {}, baseline_raw=raw
        )
        assert calls == [source]
        assert sync_plan.semantic_hash(result) == reference(path)["example/calculate"]

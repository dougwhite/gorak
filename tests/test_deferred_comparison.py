"""Byte-first comparisons retain exact native/checkpoint fallback behavior."""

import os
from pathlib import Path

import pytest
from lxml import etree

from gorak import comparison_cache, portable_source, sync_plan
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
    with (
        pytest.raises(ProjectError, match="Baseline changed"),
        comparison_cache.scope(),
        cached_source_scope(),
    ):
        values, _ = sync_plan.baseline_inventory(tmp_path)
        # Materialize only the application so the XML index is already populated.
        sync_plan.semantic_hash(values["example"])
        path.write_bytes(path.read_bytes().replace(b"RETURN 1;", b"RETURN 2;"))
        os.utime(path, ns=(original_time, original_time))
        sync_plan.semantic_hash(values["example/calculate"])
        pytest.fail("The changed component must fail before scope completion")


@pytest.mark.parametrize("change_time_moves", [False, True])
def test_deferred_resolution_verifies_bytes_even_when_stat_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change_time_moves: bool
) -> None:
    path = baseline_file(tmp_path)
    original = path.stat()
    generation = [1]
    monkeypatch.setattr(
        portable_source,
        "_source_stamp",
        lambda path: (original.st_mtime_ns, generation[0], original.st_size),
    )
    with (
        pytest.raises(ProjectError, match="Baseline changed"),
        comparison_cache.scope(),
        cached_source_scope(),
    ):
        values, _ = sync_plan.baseline_inventory(tmp_path)
        sync_plan.semantic_hash(values["example"])
        path.write_bytes(path.read_bytes().replace(b"RETURN 1;", b"RETURN 2;"))
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        generation[0] += int(change_time_moves)
        assert portable_source._source_stamp(path) == (
            original.st_mtime_ns,
            1 + int(change_time_moves),
            original.st_size,
        )
        sync_plan.semantic_hash(values["example/calculate"])
        pytest.fail("The changed component must fail before scope completion")


def test_stat_errors_do_not_reuse_cached_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = baseline_file(tmp_path)

    def unavailable(path: Path) -> tuple[int, int, int]:
        raise OSError("metadata query failed")

    with comparison_cache.scope(), cached_source_scope():
        values, _ = sync_plan.baseline_inventory(tmp_path)
        sync_plan.semantic_hash(values["example"])
        monkeypatch.setattr(portable_source, "_source_stamp", unavailable)
        with pytest.raises(ProjectError, match="Baseline changed"):
            sync_plan.semantic_hash(values["example/calculate"])
    assert path.exists()


def test_unchanged_baseline_reuses_one_parsed_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = baseline_file(tmp_path)
    reads: list[Path] = []

    def counted_read(path: Path, *, data: bytes | None = None) -> etree._Element:
        reads.append(path)
        return read_document(path, data=data)

    monkeypatch.setattr(portable_source, "_source_stamp", lambda path: (1, 1, 249))
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


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
@pytest.mark.parametrize(
    "item",
    [
        '<COMPONENT name="calculate"/>',
        '<COMPONENT name="calculate"></COMPONENT>',
        '<COMPONENT name="calculate" description="literal > and /&gt;">'
        "<script><![CDATA[literal </COMPONENT>]]></script>"
        "<!-- <COMPONENT/> --><?example value?></COMPONENT >",
    ],
)
def test_cached_source_byte_spans_are_exact(encoding: str, item: str) -> None:
    declared = "utf-8" if encoding == "utf-8-sig" else encoding
    prefix = f'<?xml version="1.0" encoding="{declared}"?><OPENROAD>'
    data = (prefix + item + "</OPENROAD>").encode(encoding)
    spans = portable_source._source_spans(data)
    assert spans is not None and len(spans) == 1
    # Encoding the isolated item must not introduce another byte order mark.
    expected = item.encode("utf-16-le" if encoding == "utf-16" else "utf-8")
    assert data[spans[0].start : spans[0].end] == expected


def test_cached_source_verifies_component_spans_and_one_full_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    components = [
        f'<COMPONENT name="item{index}"><script>x</script></COMPONENT>'
        for index in range(40)
    ]
    content = "<OPENROAD>" + "".join(components) + "</OPENROAD>"
    path = baseline_file(tmp_path, content)
    ranges: list[tuple[int, int | None]] = []
    original = portable_source._range_digest

    def measured(path: Path, start: int = 0, end: int | None = None) -> bytes:
        ranges.append((start, end))
        return original(path, start, end)

    monkeypatch.setattr(portable_source, "_range_digest", measured)
    with cached_source_scope():
        for index in range(40):
            assert (
                portable_source.cached_node_at(path, "COMPONENT", f"item{index}")
                is not None
            )
        assert all(end is not None for _, end in ranges)
    assert ranges[-1] == (0, None)
    assert len(ranges) == 41
    assert sum(end - start for start, end in ranges if end is not None) == sum(
        map(len, components)
    )


@pytest.mark.parametrize("evict", [False, True])
def test_cached_source_checks_unrequested_structure_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, evict: bool
) -> None:
    path = baseline_file(tmp_path)
    other = tmp_path / ".openroad/other/other.xml"
    other.parent.mkdir()
    other.write_text('<OPENROAD><APPLICATION name="other"/></OPENROAD>')
    monkeypatch.setattr(portable_source, "_source_stamp", lambda path: (1, 1, 249))
    with pytest.raises(ProjectError, match="Baseline changed"), cached_source_scope():
        assert (
            portable_source.cached_node_at(path, "APPLICATION", "example") is not None
        )
        # The application itself is unchanged; its surrounding namespace changed.
        path.write_bytes(path.read_bytes().replace(b"urn:unused", b"urn:edited"))
        assert (
            portable_source.cached_node_at(path, "APPLICATION", "example") is not None
        )
        if evict:
            portable_source.cached_node_at(other, "APPLICATION", "other")
            pytest.fail("Eviction must validate the previous application's XML")


def test_cached_source_refuses_changed_absence_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = baseline_file(tmp_path)
    monkeypatch.setattr(portable_source, "_source_stamp", lambda path: (1, 1, 249))
    with pytest.raises(ProjectError, match="Baseline changed"), cached_source_scope():
        assert (
            portable_source.cached_node_at(path, "APPLICATION", "example") is not None
        )
        path.write_bytes(path.read_bytes().replace(b"calculate", b"different"))
        portable_source.cached_node_at(path, "COMPONENT", "different")
        pytest.fail("Missing indexed components require whole-document verification")


def test_cached_source_checks_before_comparison_metadata_publication(
    tmp_path: Path,
) -> None:
    path = baseline_file(tmp_path)
    with (
        pytest.raises(ProjectError, match="Baseline changed"),
        comparison_cache.project_scope(tmp_path),
        cached_source_scope(),
    ):
        assert (
            portable_source.cached_node_at(path, "APPLICATION", "example") is not None
        )
        comparison_cache.save("test", "key", {"verified": True})
        path.write_bytes(path.read_bytes().replace(b"RETURN 1;", b"RETURN 2;"))
    assert not comparison_cache.storage_path(tmp_path).exists()


def test_cached_source_unsupported_span_encoding_uses_byte_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = baseline_file(tmp_path)
    data = ('<?xml version="1.0" encoding="utf-32"?>' + document()).encode("utf-32")
    path.write_bytes(data)
    assert portable_source._source_spans(data) is None
    monkeypatch.setattr(
        portable_source, "_source_stamp", lambda path: (1, 1, len(data))
    )
    with pytest.raises(ProjectError, match="Baseline changed"), cached_source_scope():
        assert (
            portable_source.cached_node_at(path, "APPLICATION", "example") is not None
        )
        path.write_bytes(
            data.replace(
                "RETURN 1;".encode("utf-32-le"), "RETURN 2;".encode("utf-32-le")
            )
        )
        portable_source.cached_node_at(path, "COMPONENT", "calculate")
        pytest.fail("Unsupported span encodings must still verify actual bytes")


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

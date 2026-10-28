"""Comparison-only stylesheet reuse keeps exact input and ownership boundaries."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest
from lxml import etree

from gorak import native_styles as styles
from gorak.errors import ProjectError


def stylesheet() -> etree._Element:
    return etree.fromstring(
        '<fielddefaults xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<row xsi:type="matrixfield"><clienttext>example</clienttext><childfields>'
        '<row xsi:type="entryfield"><name>sample</name><width>10</width></row>'
        "<row_class>formfield</row_class></childfields></row>"
        "<row_class>formfield</row_class></fielddefaults>"
    )


def counted_encoder(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[bytes], Callable[[etree._Element], dict[str, Any]]]:
    original = styles._encode_uncached
    calls: list[bytes] = []

    def encoding(node: etree._Element) -> dict[str, Any]:
        calls.append(etree.tostring(node))
        return original(node)

    monkeypatch.setattr(styles, "_encode_uncached", encoding)
    return calls, original


def counted_decoder(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[None], Callable[[dict[str, Any]], etree._Element]]:
    original = styles._decode_uncached
    calls: list[None] = []

    def decoding(value: dict[str, Any]) -> etree._Element:
        calls.append(None)
        return original(value)

    monkeypatch.setattr(styles, "_decode_uncached", decoding)
    return calls, original


def test_encode_reuses_only_identical_content_and_returns_independent_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = stylesheet()
    before = etree.tostring(source)
    calls, original = counted_encoder(monkeypatch)
    expected = original(source)
    with styles.resolution_scope():
        first = styles.encode(source)
        first["groups"]["example"]["styles"]["style1"]["width"] = "mutated"
        second = styles.encode(deepcopy(source))
        assert second == expected
        assert len(calls) == 1
        second["group_order"].clear()
        assert styles.encode(source) == expected
        source.find("row/childfields/row/width").text = "11"
        changed = styles.encode(source)
        assert changed != expected
        assert changed == original(source)
        assert len(calls) == 2
    source.find("row/childfields/row/width").text = "10"
    assert etree.tostring(source) == before
    assert styles.encode(source) == expected
    assert len(calls) == 3


def test_encode_scope_is_nested_and_released_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _ = counted_encoder(monkeypatch)
    source = stylesheet()
    with pytest.raises(RuntimeError, match="stop"), styles.resolution_scope():
        styles.encode(source)
        with styles.resolution_scope():
            styles.encode(source)
        assert len(calls) == 1
        raise RuntimeError("stop")
    assert styles._resolved.get() is None
    with styles.resolution_scope():
        styles.encode(source)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "xml",
    [
        "<wrong/>",
        "<fielddefaults>mixed<property>value</property></fielddefaults>",
        "<fielddefaults><metadata/><row/></fielddefaults>",
        "<fielddefaults><row><clienttext><?unsupported value?></clienttext></row></fielddefaults>",
    ],
)
def test_malformed_encodes_keep_errors_and_never_enter_comparison_cache(
    monkeypatch: pytest.MonkeyPatch, xml: str
) -> None:
    calls, original = counted_encoder(monkeypatch)
    source = etree.fromstring(xml)
    with pytest.raises(ProjectError) as expected:
        original(source)
    with styles.resolution_scope():
        for _ in range(2):
            with pytest.raises(ProjectError) as actual:
                styles.encode(source)
            assert str(actual.value) == str(expected.value)
        cache = styles._resolved.get()
        assert cache is not None and not cache.entries
        assert len(calls) == 2


def test_comparison_reuse_has_shared_entry_and_byte_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(styles, "_COMPARISON_MAX_ENTRIES", 3)
    monkeypatch.setattr(styles, "_COMPARISON_MAX_BYTES", 120)
    cache = styles._ComparisonStyles()
    cache.put("encode", b"one", b"a" * 20)
    cache.put("resolve", b"two", b"b" * 20)
    cache.put("encode", b"three", b"c" * 20)
    assert cache.get("encode", b"one") == b"a" * 20
    cache.put("encode", b"four", b"d" * 20)
    assert cache.get("resolve", b"two") is None
    assert len(cache.entries) == 3
    # A larger entry evicts according to bytes even below the entry count limit.
    cache.put("resolve", b"large", b"e" * 100)
    assert len(cache.entries) == 1
    assert cache.bytes <= 120
    cache.put("encode", b"too-large", b"f" * 121)
    assert cache.get("encode", b"too-large") is None
    assert cache.get("resolve", b"large") == b"e" * 100
    cache.put("resolve", b"large", b"g")
    assert cache.bytes == len("resolve") + len(b"large") + 1


def test_oversized_encoding_remains_correct_without_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(styles, "_COMPARISON_MAX_BYTES", 1)
    source = stylesheet()
    calls, original = counted_encoder(monkeypatch)
    with styles.resolution_scope():
        assert styles.encode(source) == original(source)
        assert styles.encode(source) == original(source)
        cache = styles._resolved.get()
        assert cache is not None and not cache.entries
    assert len(calls) == 2


def test_encode_without_comparison_scope_uses_original_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, original = counted_encoder(monkeypatch)
    source = stylesheet()
    assert styles.encode(source) == original(source)
    assert styles.encode(source) == original(source)
    assert len(calls) == 2


def test_decode_reuse_preserves_native_text_and_returns_independent_trees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = styles.encode(stylesheet())
    field = value["groups"]["example"]["styles"]["style1"]
    field["tooltiptext"] = " leading\r\n\x01 trailing "
    field["defaultstring"] = " literal whitespace "
    original_value = deepcopy(value)
    calls, original = counted_decoder(monkeypatch)
    expected = etree.tostring(original(value))
    with styles.resolution_scope():
        first = styles.decode(value)
        assert etree.tostring(first) == expected
        first.find("row/childfields/row/width").text = "99"
        second = styles.decode(deepcopy(value))
        assert etree.tostring(second) == expected
        second.clear()
        assert etree.tostring(styles.decode(value)) == expected
        assert len(calls) == 1
        assert value == original_value
        field["width"] = "11"
        changed = styles.decode(value)
        assert etree.tostring(changed) == etree.tostring(original(value))
        assert etree.tostring(changed) != expected
        assert len(calls) == 2
    assert etree.tostring(styles.decode(value)) == etree.tostring(original(value))
    assert len(calls) == 3


@pytest.mark.parametrize("failure", ["shape", "order", "property", "unpicklable"])
def test_malformed_decode_never_reuses_or_replaces_authoritative_error(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = styles.encode(stylesheet())
    if failure == "shape":
        value["unexpected"] = True
    elif failure == "order":
        value["group_order"] = ["example", "example"]
    elif failure == "property":
        value["groups"]["example"]["styles"]["style1"]["width"] = 17
    else:
        value["groups"]["example"]["styles"]["style1"]["width"] = lambda: None
    calls, original = counted_decoder(monkeypatch)
    with pytest.raises(ProjectError) as expected:
        original(value)
    with styles.resolution_scope():
        for _ in range(2):
            with pytest.raises(ProjectError) as actual:
                styles.decode(value)
            assert str(actual.value) == str(expected.value)
        cache = styles._resolved.get()
        assert cache is not None and not cache.entries
    assert len(calls) == 2


def test_oversized_decoded_trees_are_not_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = styles.encode(stylesheet())
    monkeypatch.setattr(styles, "_COMPARISON_MAX_BYTES", 1)
    calls, original = counted_decoder(monkeypatch)
    with styles.resolution_scope():
        for _ in range(2):
            assert etree.tostring(styles.decode(value)) == etree.tostring(
                original(value)
            )
        cache = styles._resolved.get()
        assert cache is not None and not cache.entries
    assert len(calls) == 2


def test_decode_without_comparison_scope_uses_original_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = styles.encode(stylesheet())
    calls, original = counted_decoder(monkeypatch)
    assert etree.tostring(styles.decode(value)) == etree.tostring(original(value))
    assert etree.tostring(styles.decode(value)) == etree.tostring(original(value))
    assert len(calls) == 2

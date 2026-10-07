"""Performance shortcuts preserve validation, snapshot isolation and diagnostics."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from gorak import native_styles, portable_source
from gorak.bitmap_codec import decode_buffer, encode_buffer
from gorak.errors import ProjectError
from gorak.export_progress import EncodingProgress


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_buffer_wrapping_offsets_and_trailing_metadata(newline: str) -> None:
    pixels = bytes(range(256)) + b"x" * 300 + b"y" * 18
    encoded = encode_buffer(pixels).replace("\n", "")
    wrapped = newline.join(encoded[i : i + 3] for i in range(0, len(encoded), 3))
    decoded, offset = decode_buffer("prefix" + wrapped + "\n123456\n", 6, len(pixels))
    assert decoded == pixels
    assert offset == 6 + len(wrapped)


def test_buffer_rejects_overlong_runs_before_allocating() -> None:
    with pytest.raises(ProjectError, match="exceeds"):
        decode_buffer("R4ffffffff00", 0, 1)
    for invalid in ["a", "r!00", "aa bb", "r000X", "R0"]:
        with pytest.raises(ProjectError):
            decode_buffer(invalid, 0, 100)


def test_source_index_reuses_parse_and_returns_independent_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "example"
    cache = tmp_path / ".openroad" / "example"
    cache.mkdir(parents=True)
    xml = cache / "example.xml"
    xml.write_text(
        '<OPENROAD><APPLICATION name="example"/><COMPONENT name="one"/><COMPONENT name="two"/></OPENROAD>'
    )
    reader = Mock(wraps=portable_source.read_document)
    monkeypatch.setattr(portable_source, "read_document", reader)
    with portable_source.cached_source_scope():
        first = portable_source.cached_node(app, "COMPONENT", "one")
        assert first is not None
        first.set("name", "edited")
        again = portable_source.cached_node(app, "COMPONENT", "one")
        assert again is not None and again.get("name") == "one"
        assert portable_source.cached_node(app, "COMPONENT", "two") is not None
        assert reader.call_count == 1
        xml.write_text('<OPENROAD><APPLICATION name="example"/></OPENROAD>')
        assert portable_source.cached_node(app, "COMPONENT", "one") is None
        assert reader.call_count == 2
    portable_source.cached_node(app, "COMPONENT", "one")
    assert reader.call_count == 3


def test_style_validation_cache_detects_mutations_and_ends_with_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value: native_styles.Json = {"properties": {}, "group_order": [], "groups": {}}
    decoder = Mock(wraps=native_styles.decode)
    monkeypatch.setattr(native_styles, "decode", decoder)
    with native_styles.validation_scope():
        native_styles.validate(value)
        native_styles.validate(value)
        assert decoder.call_count == 1
        value["properties"] = {"_text": 123}
        with pytest.raises(ProjectError):
            native_styles.validate(value)
        value["properties"] = {}
    native_styles.validate(value)
    assert decoder.call_count == 3


def test_bulk_progress_throttles_and_reports_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gorak import export_progress

    now = [0.0]
    monkeypatch.setattr(export_progress, "monotonic", lambda: now[0])
    messages: list[str] = []
    progress = EncodingProgress("example", 100, messages.append)
    progress.before("first")
    progress.completed(1)
    assert messages == ["Encoding example: 0/100 components"]
    now[0] = 5.0
    progress.completed(25)
    assert messages[-1].endswith("5s elapsed, about 15s remaining")
    now[0] = 6.0
    progress.completed(100)
    assert messages[-1] == "Encoding example: 100/100 components, 6s elapsed"

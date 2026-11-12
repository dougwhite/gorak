import hashlib
from pathlib import Path

import pytest

from gorak.source_output import write_text


@pytest.mark.parametrize("newline", [None, "\n", "\r\n"])
def test_output_matches_text_io_bytes(tmp_path: Path, newline: str | None) -> None:
    text = "Unicode 日本語\nline\r\nlast\r"
    expected = tmp_path / "expected"
    expected.write_text(text, encoding="utf-8", newline=newline)
    actual = tmp_path / "actual"
    captured: dict[Path, str] = {}
    write_text(actual, text, newline=newline, digests=captured)
    assert actual.read_bytes() == expected.read_bytes()
    assert captured[actual] == hashlib.sha256(expected.read_bytes()).hexdigest()

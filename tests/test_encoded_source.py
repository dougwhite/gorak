import json
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from gorak.encoded_source import (
    PREFIX,
    SUFFIX,
    UnsupportedSource,
    assemble_chunks,
    decode_procedure,
    read_procedure,
)
from gorak.importer import signature
from tests.test_affected_source import SETTINGS, Engine

FIXTURES = Path(__file__).parent / "fixtures/encoded_source"


def payload(script: str) -> str:
    return PREFIX + str(len(script)) + ":" + script + SUFFIX


@pytest.mark.parametrize("name", ["initial", "edited", "long"])
def test_live_synthetic_chunks_match_complete_xml_oracle(name: str) -> None:
    rows = json.loads((FIXTURES / f"{name}.json").read_text())
    reference = etree.parse(str(FIXTURES / f"{name}.xml")).getroot()
    source = decode_procedure(assemble_chunks(list(reversed(rows))))
    assert signature(
        source.component("probe", reference.findtext("versshortremarks", ""))
    ) == signature(reference)


def test_delimiters_inside_script_are_length_delimited() -> None:
    script = "\n$\n=\n12:stringobject\n4\n1\n\n0\n5:hello\n  \t"
    assert decode_procedure(payload(script)).script == script


def test_xml_newline_normalization_matches_oracle() -> None:
    assert decode_procedure(payload("a\r\nb\rc")).script == "a\nb\nc"


@pytest.mark.parametrize(
    "fault", ["length", "tail", "compiled", "unicode", "nul", "version"]
)
def test_unknown_or_corrupt_graph_requests_fallback(fault: str) -> None:
    value = payload("abc")
    if fault == "length":
        value = value.replace("3:abc", "4:abc")
    elif fault == "tail":
        value += "junk"
    elif fault == "compiled":
        value = value.replace("6\n0\n-1:", "6\n2\n-1:")
    elif fault == "unicode":
        value = payload("caf\u00e9")
    elif fault == "nul":
        value = payload("a\x00b")
    else:
        value = value.replace("Source Object\n1", "Source Object\n2")
    with pytest.raises(UnsupportedSource):
        decode_procedure(value)


@pytest.mark.parametrize(
    "rows",
    [[], [(1, 1, "a")], [(1, 0, "a"), (1, 0, "b")], [(2, 0, "a")], [(1, 0, "")]],
)
def test_missing_duplicate_or_unknown_chunks_rejected(
    rows: list[tuple[int, int, str]],
) -> None:
    with pytest.raises(UnsupportedSource):
        assemble_chunks(rows)


def test_candidate_query_is_bounded_and_parameterized() -> None:
    class SourceEngine(Engine):
        def execute(self, query: Any, params: Any = None) -> "SourceEngine":
            self.queries.append(str(query))
            if params:
                assert params == {"entity_id": 12}
            return self

    engine = SourceEngine([[1, 0, payload("abc")]])
    assert read_procedure(SETTINGS, 12, lambda _: engine).script == "abc"
    assert "where entity_id=:entity_id" in engine.queries[-1]
    assert "select first 1025" in engine.queries[-1]
    assert engine.closed and engine.disposed


def test_chunk_budget_and_script_crossing_chunk_boundary() -> None:
    script = "  // delimiter $\n" * 200
    value = payload(script)
    rows = [(1, i // 1790, value[i : i + 1790]) for i in range(0, len(value), 1790)]
    assert decode_procedure(assemble_chunks(rows)).script == script
    with pytest.raises(UnsupportedSource, match="budget"):
        assemble_chunks([(1, i, "a" * 1790) for i in range(600)])


def test_long_or_noncanonical_length_is_rejected() -> None:
    for length in ("0003", "-1", "999999999999999999999999", ""):
        with pytest.raises(UnsupportedSource):
            decode_procedure(PREFIX + length + ":abc" + SUFFIX)

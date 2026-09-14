import json
from dataclasses import replace
from pathlib import Path

import pytest

from gorak.encoded_graph import UnsupportedSource
from gorak.encoded_source import assemble_chunks, decode_procedure
from gorak.storage_graph import Limits, Literal, Verbatim, decode, encode

FIXTURES = Path(__file__).parent / "fixtures/encoded_source"


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_reencodes_entire_synthetic_graph_exactly(path: Path) -> None:
    payload = assemble_chunks(json.loads(path.read_text()))
    assert encode(decode(payload)) == payload


def simple(body: str) -> str:
    return "1\n14: Source Object\n1\n\n12:stringobject\n1\n1\n\n0\n" + body + "\n$\n=\n"


def test_preserves_null_empty_delimiters_and_opaque_image_data() -> None:
    payload = simple("-1:\n0:\n4:$\n=\n\nR1cffr0\n\x7f\x7f2\n")
    graph = decode(payload)
    assert [f.value for f in graph.records[0].fields if isinstance(f, Literal)] == [
        None,
        "",
        "$\n=\n",
    ]
    assert encode(graph) == payload


def test_length_edit_preserves_other_records_and_decodes_as_procedure() -> None:
    original = assemble_chunks(json.loads((FIXTURES / "initial.json").read_text()))
    graph = decode(original)
    script_record = next(r for r in graph.records if r.kind == "stringobject")
    script = "PROCEDURE probe() = { RETURN 1; }\n// $\n// =\n"
    edited = graph.replace_string(script_record.identity, 0, script)
    result = encode(edited)
    assert decode_procedure(result).script == script
    assert all(
        a == b
        for a, b in zip(graph.records, edited.records, strict=True)
        if a.identity != script_record.identity
    )
    assert encode(graph) == original


@pytest.mark.parametrize("body", ["-2:\n", "01:a\n", "4:ab\n", "99:a\n"])
def test_rejects_bad_string_lengths(body: str) -> None:
    with pytest.raises(UnsupportedSource):
        decode(simple(body))


@pytest.mark.parametrize(
    "old,new",
    [
        ("1\n14:", "2\n14:"),
        ("1\n14:", "0\n14:"),
        ("1\n14:", "100001\n14:"),
        (" Source Object", " Unknown Graph"),
        ("stringobject\n1", "stringobject\n2"),
        ("\n$\n", "\n"),
        ("=\n", "=\nextra\n"),
    ],
)
def test_rejects_incomplete_or_inconsistent_framing(old: str, new: str) -> None:
    with pytest.raises(UnsupportedSource):
        decode(simple("0:\n").replace(old, new, 1))


def test_explicit_resource_limits_and_unproven_unicode() -> None:
    payload = simple("0:\n")
    with pytest.raises(UnsupportedSource):
        decode(payload, Limits(characters=len(payload) - 1))
    with pytest.raises(UnsupportedSource):
        decode(payload, Limits(strings=2))
    with pytest.raises(UnsupportedSource):
        decode(simple("1:é\n"))


def test_rejects_raw_delimiter_injection_and_forged_header() -> None:
    graph = decode(simple("0:\n"))
    record = graph.records[0]
    injected = replace(record, fields=(Verbatim("\n$\n"),))
    with pytest.raises(UnsupportedSource):
        encode(replace(graph, records=(injected,)))
    forged = replace(record, identity=2)
    with pytest.raises(UnsupportedSource):
        encode(replace(graph, records=(forged,)))


def test_encoder_enforces_budget_after_string_edit() -> None:
    graph = decode(simple("0:\n")).replace_string(1, 0, "a" * 1000)
    with pytest.raises(UnsupportedSource):
        encode(graph, Limits(characters=100))


@pytest.mark.parametrize("identity,index", [(0, 0), (2, 0), (1, -1), (1, 1)])
def test_string_selection_must_be_unambiguous(identity: int, index: int) -> None:
    with pytest.raises(UnsupportedSource):
        decode(simple("0:\n")).replace_string(identity, index, "x")


def test_large_embedded_image_and_multichunk_script_framing() -> None:
    image = "R1cffr0\n" * 150_000
    script = "// embedded $\n=\n12:stringobject\n" * 1000
    payload = simple(image + f"{len(script)}:{script}\n")
    assert len(payload) > 1024 * 1024
    assert encode(decode(payload)) == payload

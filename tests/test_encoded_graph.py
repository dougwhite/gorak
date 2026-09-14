import json
from pathlib import Path

import pytest

from gorak.encoded_graph import Reader, UnsupportedSource, read_graph
from gorak.encoded_source import assemble_chunks, decode_procedure

FIXTURES = Path(__file__).parent / "fixtures/encoded_source"


def graph(name: str = "compiled_zero") -> str:
    return assemble_chunks(json.loads((FIXTURES / (name + ".json")).read_text()))


def test_compilation_changes_storage_not_decoded_source() -> None:
    initial = assemble_chunks(json.loads((FIXTURES / "initial.json").read_text()))
    compiled = graph()
    assert initial != compiled
    assert decode_procedure(initial).script == decode_procedure(compiled).script


def test_resolves_script_reference_instead_of_record_position() -> None:
    value = graph()
    # Exchange two complete auxiliary records; object IDs carry identity.
    left = "3:bag\n6\n1\n\n2\n10\n0\n6:object\n\n$\n"
    right = "3:bag\n7\n1\n\n2\n10\n0\n11:taggedvalue\n\n$\n"
    assert left + right in value
    assert read_graph(value.replace(left + right, right + left)) == read_graph(value)


@pytest.mark.parametrize(
    "old,new",
    [
        ("10\n14:", "11\n14:"),
        ("10\n14:", "513\n14:"),
        ("8:ilobject\n2\n1", "8:ilobject\n2\n2"),
        ("8:ilobject\n2\n1", "8:ilobject\n3\n1"),
        ("1\n3\n5\n+2++", "1\n3\n6\n+2++"),
        ("1\n3\n5\n+2++", "1\n3\n5\n+2+z"),
        ("1\n3\n5\n+2++", "2\n3\n5\n+2++"),
        ("4\n8\n3\n9\n10", "4\n2\n3\n9\n10"),
        ("14\n45\n8\n0\n3\n0\n5", "14\n45\n8\n0\n3\n0\n4"),
        ("14\n45\n8\n0\n3\n0\n5", "14\n45\n8\n0\n99\n0\n5"),
        ("11:scopesymtab", "11:unknownclas"),
        ("0\n0\n-1\n0\n\n$", "0\n0\n-1\n0\n1\n\n$"),
        ("0\n0\n0\n0\n1\n3\n6", "0\n0\n1\n0\n1\n3\n6"),
    ],
)
def test_invalid_or_unknown_compiler_graph_requires_xml(old: str, new: str) -> None:
    value = graph()
    assert old in value
    with pytest.raises(UnsupportedSource):
        read_graph(value.replace(old, new, 1))


def test_script_delimiters_cannot_inject_objects() -> None:
    value = graph()
    script = "PROCEDURE probe() = { RETURN 0; }"
    edited = script + "\n// 12:stringobject\n$\n=\n"
    value = value.replace(f"{len(script)}:{script}", f"{len(edited)}:{edited}")
    assert read_graph(value)[0] == edited


def test_compiled_name_must_match_current_entity() -> None:
    source = decode_procedure(graph())
    with pytest.raises(UnsupportedSource, match="name_mismatch"):
        source.component("other", "description")


def test_packed_integer_array_preserves_wrapped_byte_count() -> None:
    Reader("2\n3\n10\n1+2+\n++++\n").packed(3)
    with pytest.raises(UnsupportedSource):
        Reader("2\n3\n9\n1+2+\n++++\n").packed(3)


def test_cli_generated_literal_pool_remains_explicitly_unsupported() -> None:
    with pytest.raises(UnsupportedSource, match="unsupported_graph_layout"):
        read_graph(graph("unsupported_pool"))


def test_shortened_compiler_record_cannot_hide_missing_fields() -> None:
    value = graph()
    value = value.replace("0\n0\n-1\n0\n\n$", "0\n0\n-1\n\n$", 1)
    with pytest.raises(UnsupportedSource):
        read_graph(value)

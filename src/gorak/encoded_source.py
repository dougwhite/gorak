"""Strict first slice of OpenROAD 12 procedure source decoding.

Only the experimentally verified, uncompiled integer-procedure graph is accepted.
Unknown layouts, compiled graphs, external strings and non-ASCII payloads explicitly
request XML fallback. This is intentionally not a general object deserializer.
"""

from dataclasses import dataclass

from lxml import etree
from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine

MAX_CHUNKS = 1024
MAX_CHARACTERS = 1024 * 1024
PREFIX = (
    "6\n14: Source Object\n1\n\n13:proc4glsource\n1\n1\n\n"
    "6\n0\n-1:\n2\n0\n3\n\n1\n\n4\n4\n0\n5\n6\n0\n-1:\n\n$\n"
    "3:bag\n2\n1\n\n2\n10\n0\n6:object\n\n$\n"
    "3:bag\n3\n1\n\n2\n10\n0\n11:taggedvalue\n\n$\n"
    "12:stringobject\n4\n1\n\n0\n"
)
SUFFIX = (
    "\n\n$\n3:bag\n5\n1\n\n2\n10\n0\n13:macrovariable\n\n$\n"
    "3:bag\n6\n1\n\n2\n10\n0\n11:queryobject\n\n$\n=\n"
)


class UnsupportedSource(ValueError):
    """The caller must use its complete XML observation, never a partial result."""


@dataclass(frozen=True)
class ProcedureSource:
    script: str

    def component(self, name: str, description: str) -> etree._Element:
        node = etree.Element(
            "COMPONENT",
            name=name,
            nsmap={"xsi": "http://www.w3.org/2001/XMLSchema-instance"},
        )
        node.set("{http://www.w3.org/2001/XMLSchema-instance}type", "proc4glsource")
        if description:
            etree.SubElement(node, "versshortremarks").text = description
        etree.SubElement(node, "script").text = self.script
        etree.SubElement(node, "datatype").text = "integer"
        return node


def decode_procedure(payload: str) -> ProcedureSource:
    """Consume the complete graph, honoring string length rather than delimiters."""
    if (
        len(payload) > MAX_CHARACTERS
        or not payload.isascii()
        or "\x00" in payload
        or not payload.startswith(PREFIX)
    ):
        raise UnsupportedSource("unsupported_procedure_layout_or_encoding")
    start = len(PREFIX)
    colon = payload.find(":", start, start + 9)
    length_text = payload[start:colon]
    if colon < 0 or not length_text.isdecimal() or str(int(length_text)) != length_text:
        raise UnsupportedSource("invalid_script_length")
    length = int(length_text)
    end = colon + 1 + length
    if length > MAX_CHARACTERS or payload[end:] != SUFFIX:
        raise UnsupportedSource("invalid_script_boundary_or_graph_tail")
    script = payload[colon + 1 : end]
    # XML parsers normalize CR/CRLF; retain that same XML-oracle meaning.
    script = script.replace("\r\n", "\n").replace("\r", "\n")
    if any(ord(c) < 32 and c not in "\n\t" for c in script):
        raise UnsupportedSource("invalid_xml_script_character")
    return ProcedureSource(script)


def assemble_chunks(rows: list[tuple[int, int, str]]) -> str:
    """Assemble subtype 1, contiguous zero-based chunks without stripping content."""
    if not rows or len(rows) > MAX_CHUNKS:
        raise UnsupportedSource("missing_or_over_budget_chunks")
    chunks: dict[int, str] = {}
    size = 0
    for subtype, sequence, value in rows:
        if (
            type(subtype) is not int
            or subtype != 1
            or type(sequence) is not int
            or sequence < 0
            or sequence in chunks
            or not isinstance(value, str)
            or not 1 <= len(value) <= 1790
        ):
            raise UnsupportedSource("invalid_or_duplicate_source_chunk")
        chunks[sequence] = value
        size += len(value)
        if size > MAX_CHARACTERS:
            raise UnsupportedSource("encoded_source_budget_exceeded")
    if set(chunks) != set(range(len(chunks))):
        raise UnsupportedSource("noncontiguous_source_chunks")
    return "".join(chunks[index] for index in range(len(chunks)))


def read_procedure(
    settings: OdbcSettings,
    entity_id: int,
    engine_factory: EngineFactory = create_odbc_engine,
) -> ProcedureSource:
    """Read only one resolved current entity; caller owns revision/identity guards."""
    if type(entity_id) is not int or entity_id <= 0:
        raise UnsupportedSource("invalid_source_entity_id")
    engine = engine_factory(settings)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "set lockmode session where level=mvcc, readlock=shared, timeout=5"
                )
            )
            result = connection.execute(
                text(
                    f"select first {MAX_CHUNKS + 1} sub_type,sequence_no,text_string "
                    'from "$ingres".ii_srcobj_encoded where entity_id=:entity_id'
                ),
                {"entity_id": entity_id},
            )
            try:
                rows = result.fetchmany(MAX_CHUNKS + 1)
            finally:
                result.close()
        return decode_procedure(assemble_chunks([tuple(row) for row in rows]))
    finally:
        engine.dispose()

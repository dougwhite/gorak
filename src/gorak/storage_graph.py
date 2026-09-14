"""Lossless framing of ASCII source graphs, independent of class semantics.

Strings are length-delimited. Other field data is preserved verbatim, including
compiler arrays, nullable values and image encodings. Framing success does NOT
certify field meanings, references, portability or permission to write a database.
"""

import re
from dataclasses import dataclass, replace

from .encoded_graph import UnsupportedSource

_LENGTH = re.compile(r"(-1|0|[1-9][0-9]{0,8}):")
_INTEGER = re.compile(r"(?:0|[1-9][0-9]{0,8})\n")
_CLASS = re.compile(r"[a-z][a-z0-9_]{0,127}")


@dataclass(frozen=True)
class Limits:
    characters: int = 64 * 1024 * 1024
    objects: int = 100_000
    strings: int = 1_000_000


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class Literal:
    """A nullable length-delimited string, without its terminating newline."""

    value: str | None


@dataclass(frozen=True)
class Verbatim:
    """Uninterpreted field bytes; never assume integers here are references."""

    value: str


Field = Literal | Verbatim


@dataclass(frozen=True)
class Record:
    kind: str
    identity: int
    version: int
    fields: tuple[Field, ...]
    # Preserve header spacing independently from editable body fields.
    header: str


@dataclass(frozen=True)
class Graph:
    records: tuple[Record, ...]
    header: str
    ending: str

    def replace_string(self, identity: int, index: int, value: str | None) -> "Graph":
        """Explicit structural edit; callers must first establish field ownership."""
        records = list(self.records)
        matches = [i for i, r in enumerate(records) if r.identity == identity]
        if len(matches) != 1 or index < 0:
            raise UnsupportedSource("invalid_graph_string_selection")
        position = matches[0]
        record = records[position]
        fields = list(record.fields)
        strings = [i for i, field in enumerate(fields) if isinstance(field, Literal)]
        if index >= len(strings):
            raise UnsupportedSource("invalid_graph_string_selection")
        fields[strings[index]] = Literal(value)
        records[position] = replace(record, fields=tuple(fields))
        return replace(self, records=tuple(records))


class _Cursor:
    def __init__(self, source: str, limits: Limits):
        self.source = source
        self.position = 0
        self.strings = 0
        self.limits = limits

    def blanks(self) -> None:
        while self.source[self.position : self.position + 1] == "\n":
            self.position += 1

    def integer(self) -> int:
        self.blanks()
        match = _INTEGER.match(self.source, self.position)
        if match is None:
            raise UnsupportedSource("invalid_graph_header_integer")
        self.position = match.end()
        return int(match[0])

    def literal(self) -> Literal:
        match = _LENGTH.match(self.source, self.position)
        if match is None:
            raise UnsupportedSource("invalid_graph_string_length")
        size = int(match[1])
        start = match.end()
        end = start + max(size, 0)
        if end >= len(self.source) or self.source[end] != "\n":
            raise UnsupportedSource("invalid_graph_string_boundary")
        self.strings += 1
        if self.strings > self.limits.strings:
            raise UnsupportedSource("graph_string_budget_exceeded")
        self.position = end + 1
        return Literal(None if size == -1 else self.source[start:end])


def decode(payload: str, limits: Limits = DEFAULT_LIMITS) -> Graph:
    """Consume complete framing; retain opaque body fields without interpreting them."""
    if (
        len(payload) > limits.characters
        or not payload.isascii()
        or "\x00" in payload
        or limits.objects < 1
    ):
        raise UnsupportedSource("unsupported_storage_graph_size_or_encoding")
    cursor = _Cursor(payload, limits)
    count = cursor.integer()
    if not 1 <= count <= limits.objects:
        raise UnsupportedSource("graph_object_budget_exceeded")
    cursor.blanks()
    if cursor.literal().value != " Source Object" or cursor.integer() != 1:
        raise UnsupportedSource("unsupported_storage_graph_header")
    cursor.blanks()
    header = payload[: cursor.position]
    records = []
    identities: set[int] = set()
    for _ in range(count):
        start = cursor.position
        cursor.blanks()
        kind = cursor.literal().value
        identity = cursor.integer()
        version = cursor.integer()
        if (
            kind is None
            or not _CLASS.fullmatch(kind)
            or not 1 <= identity <= count
            or identity in identities
        ):
            raise UnsupportedSource("invalid_storage_object_header")
        identities.add(identity)
        record_header = payload[start : cursor.position]
        fields: list[Field] = []
        raw_start = cursor.position
        while True:
            pos = cursor.position
            if payload.startswith("$\n", pos):
                if pos > raw_start:
                    fields.append(Verbatim(payload[raw_start:pos]))
                cursor.position += 2
                break
            if pos >= len(payload) or payload.startswith("=\n", pos):
                raise UnsupportedSource("truncated_storage_object")
            if _LENGTH.match(payload, pos):
                if pos > raw_start:
                    fields.append(Verbatim(payload[raw_start:pos]))
                fields.append(cursor.literal())
                raw_start = cursor.position
            else:
                end = payload.find("\n", pos)
                if end < 0:
                    raise UnsupportedSource("truncated_storage_field")
                # A malformed length prefix must not be laundered as opaque data.
                line = payload[pos:end]
                if re.match(r"-?[0-9]+:", line):
                    raise UnsupportedSource("invalid_graph_string_length")
                cursor.position = end + 1
        records.append(Record(kind, identity, version, tuple(fields), record_header))
    ending = payload[cursor.position :]
    if ending.lstrip("\n") != "=\n":
        raise UnsupportedSource("invalid_storage_graph_end")
    return Graph(tuple(records), header, ending)


def encode(graph: Graph, limits: Limits = DEFAULT_LIMITS) -> str:
    """Re-encode framed fields and validate structure, not database write semantics."""
    parts = [graph.header]
    size = len(graph.header) + len(graph.ending)
    for record in graph.records:
        parts.append(record.header)
        size += len(record.header) + 2
        for field in record.fields:
            if isinstance(field, Literal):
                value = field.value
                part = "-1:\n" if value is None else f"{len(value)}:{value}\n"
            else:
                part = field.value
            size += len(part)
            if size > limits.characters:
                raise UnsupportedSource("storage_graph_encoding_budget_exceeded")
            parts.append(part)
        parts.append("$\n")
    parts.append(graph.ending)
    result = "".join(parts)
    # Reject edited headers, injected delimiters and malformed opaque field edits.
    if decode(result, limits) != graph:
        raise UnsupportedSource("storage_graph_structure_changed")
    return result

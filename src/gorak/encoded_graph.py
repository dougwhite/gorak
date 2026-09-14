"""Bounded reader for the observed OpenROAD 12 integer-procedure graph.

Compiler records are structurally validated, not executed or interpreted as source.
Unknown layouts, literal pools and symbol types explicitly request XML fallback.
"""

import re
from dataclasses import dataclass

MAX_OBJECTS = 512
MAX_SIZE = 1024 * 1024
STRING_LENGTH = re.compile(r"(-1|0|[1-9][0-9]{0,6}):")


class UnsupportedSource(ValueError):
    """The caller must use complete XML rather than a partial decoded result."""


@dataclass
class Reader:
    source: str
    position: int = 0

    def blanks(self) -> None:
        while self.source[self.position : self.position + 1] == "\n":
            self.position += 1

    def line(self) -> str:
        self.blanks()
        end = self.source.find("\n", self.position)
        if end < 0:
            raise UnsupportedSource("truncated_graph_record")
        value = self.source[self.position : end]
        self.position = end + 1
        return value

    def number(self) -> int:
        value = self.line()
        if not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,9})", value):
            raise UnsupportedSource("invalid_graph_integer")
        result = int(value)
        if str(result) != value:
            raise UnsupportedSource("noncanonical_graph_integer")
        return result

    def numbers(self, *values: int) -> None:
        if any(self.number() != value for value in values):
            raise UnsupportedSource("unsupported_graph_layout")

    def string(self) -> str | None:
        self.blanks()
        match = STRING_LENGTH.match(self.source, self.position)
        if match is None:
            raise UnsupportedSource("invalid_graph_string_length")
        size = int(match[1])
        self.position = match.end()
        end = self.position + max(0, size)
        if end >= len(self.source) or self.source[end] != "\n":
            raise UnsupportedSource("invalid_graph_string_boundary")
        value = self.source[self.position : end]
        self.position = end + 1
        return None if size == -1 else value

    def expect_string(self, value: str | None) -> None:
        if self.string() != value:
            raise UnsupportedSource("unsupported_graph_string")

    def packed(self, columns: int) -> None:
        rows = self.number()
        if rows == 0:
            return
        if not 1 <= rows <= MAX_SIZE or self.number() != columns:
            raise UnsupportedSource("unsupported_compiler_array")
        size = self.number()
        if not 1 <= size <= MAX_SIZE:
            raise UnsupportedSource("compiler_array_budget_exceeded")
        end = self.position + size
        data = self.source[self.position : end]
        if end > len(self.source) or not data.endswith("\n"):
            raise UnsupportedSource("truncated_compiler_array")
        packed = data.replace("\n", "")
        values = re.findall(r"[0-9a-f]{0,16}[+-]", packed)
        if "".join(values) != packed or len(values) != rows * columns:
            raise UnsupportedSource("invalid_compiler_array_length")
        self.position = end


def read_graph(payload: str) -> tuple[str, str | None]:
    if len(payload) > MAX_SIZE or not payload.isascii() or "\x00" in payload:
        raise UnsupportedSource("unsupported_procedure_layout_or_encoding")
    r = Reader(payload)
    count = r.number()
    if not 1 <= count <= MAX_OBJECTS:
        raise UnsupportedSource("graph_object_budget_exceeded")
    r.expect_string(" Source Object")
    r.numbers(1)
    kinds: dict[int, str] = {}
    bags: dict[int, str | None] = {}
    scripts: dict[int, str | None] = {}
    symbols: dict[int, tuple[int, int, str | None]] = {}
    scopes: dict[int, tuple[str | None, list[int], int]] = {}
    root: tuple[int, ...] | None = None
    for index in range(count):
        kind = r.string()
        identity = r.number()
        if not kind or not 1 <= identity <= count or identity in kinds:
            raise UnsupportedSource("invalid_graph_object_identity")
        kinds[identity] = kind
        r.numbers(1)  # Known object serialization version.
        if kind == "proc4glsource" and index == 0 and identity == 1:
            r.numbers(6)
            il = r.number()
            r.expect_string(None)
            objects = r.number()
            r.numbers(0)
            tagged = r.number()
            r.numbers(1, 4)  # Observed nonnullable integer source form.
            script, scope, macros, queries = (r.number() for _ in range(4))
            r.numbers(0)
            r.expect_string(None)
            root = il, objects, tagged, script, scope, macros, queries
        elif kind == "bag":
            r.numbers(2, 10, 0)  # Only empty auxiliary bags are supported.
            bags[identity] = r.string()
        elif kind == "stringobject":
            r.numbers(0)
            scripts[identity] = r.string()
        elif kind == "ilobject":
            r.numbers(3)
            for columns in (3, 7, 6, 1, 1):
                r.packed(columns)
            r.numbers(0, 0, 0, 0)  # Literal pools remain unsupported.
            r.packed(3)
            r.numbers(0, 0, -1, 0)
        elif kind == "scopesymtab":
            r.numbers(0)
            name = r.string()
            r.numbers(0, 0, 1, 31)
            buckets = [r.number() for _ in range(31)]
            symbol_count = r.number()
            r.numbers(1, 0, 0, 0)
            scopes[identity] = name, buckets, symbol_count
        elif kind in {"symfrmvar", "symvariable"}:
            frame = kind == "symfrmvar"
            r.numbers(5, 0 if frame else 1, 0)
            name = r.string()
            r.numbers(*(14, 45, 8, 0) if frame else (1, -30, 5, 0))
            scope = r.number()
            r.numbers(0)
            next_symbol = r.number()
            r.expect_string("iisystem!procexec" if frame else "integer")
            r.numbers(0, 16384 if frame else 8232, 4, 0)
            r.expect_string(None)
            r.numbers(2 if frame else 1)
            r.expect_string(None)
            if frame:
                r.numbers(0)
                if name not in {"curprocedure", "curexec"}:
                    raise UnsupportedSource("unsupported_compiler_frame_symbol")
            if not name:
                raise UnsupportedSource("invalid_compiler_symbol_name")
            symbols[identity] = scope, next_symbol, name
        else:
            raise UnsupportedSource("unsupported_graph_object_class")
        if r.source[r.position : r.position + 3] != "\n$\n":
            raise UnsupportedSource("unexpected_graph_record_tail")
        r.position += 3
    if r.line() != "=" or r.position != len(payload) or root is None:
        raise UnsupportedSource("invalid_graph_end")
    il, objects, tagged, script, scope, macros, queries = root
    expected_bags = dict(
        zip(
            (objects, tagged, macros, queries),
            ("object", "taggedvalue", "macrovariable", "queryobject"),
            strict=True,
        )
    )
    if (
        len(expected_bags) != 4
        or bags != expected_bags
        or set(scripts) != {script}
        or scripts[script] is None
    ):
        raise UnsupportedSource("invalid_source_graph_references")
    used = {1, *expected_bags, script}
    compiled_name = None
    if il or scope:
        if kinds.get(il) != "ilobject" or set(scopes) != {scope}:
            raise UnsupportedSource("invalid_compiler_root_references")
        compiled_name, buckets, symbol_count = scopes[scope]
        visited: set[int] = set()
        names: set[str] = set()
        for head in buckets:
            while head:
                if head in visited or head not in symbols:
                    raise UnsupportedSource("invalid_compiler_symbol_reference")
                visited.add(head)
                owner, head, name = symbols[head]
                if owner != scope or not name or name in names:
                    raise UnsupportedSource("invalid_compiler_symbol_scope")
                names.add(name)
        frame_names = {
            symbols[identity][2]
            for identity in symbols
            if kinds[identity] == "symfrmvar"
        }
        if (
            visited != set(symbols)
            or symbol_count != len(visited)
            or not compiled_name
            or frame_names != {"curprocedure", "curexec"}
        ):
            raise UnsupportedSource("incomplete_compiler_symbol_table")
        used.update((il, scope, *symbols))
    if used != set(kinds):
        raise UnsupportedSource("unreferenced_graph_objects")
    script_text = scripts[script]
    assert script_text is not None
    return script_text, compiled_name

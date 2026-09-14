"""Compose explicit writer startup artifacts; no environment or file mutations."""

import re
from collections.abc import Callable
from pathlib import PurePosixPath, PureWindowsPath

from .project import ProjectError

# This scanner validates statement boundaries, not the complete Ingres SET grammar.
_TOKEN = re.compile(
    r"\s+|--[^\r\n]*(?:\r?\n|$)|/\*.*?\*/|'(?:''|[^'])*'|"
    r'"(?:""|[^"])*"|[A-Za-z_$][A-Za-z_0-9$]*|.',
    re.DOTALL,
)


def counter_table_name(table: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", table):
        raise ProjectError("Invalid counter table identifier")
    return f'"$ingres".{table}'


def compose_writer_init(
    existing: str,
    table: str,
    *,
    read_include: Callable[[str], str] | None = None,
) -> str:
    """Preserve startup statements and append a counter-table MVCC/shared override.

    An include resolver must operate on the execution host. Never interpret a
    remote include as a local file. Nested includes and non-SET input are rejected.
    The caller owns encoding, exclusive artifact creation and environment scoping.
    """
    qualified = counter_table_name(table)
    match = re.match(r"^\s*include\s+(.+?)\s*$", existing, re.IGNORECASE)
    if match:
        path = match[1]
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if (
            any(c in path for c in '\r\n\0"')
            or not (
                PureWindowsPath(path).is_absolute() or PurePosixPath(path).is_absolute()
            )
            or read_include is None
        ):
            raise ProjectError(
                "Startup include requires an absolute execution-host path and resolver"
            )
        existing = read_include(path)
    if "\0" in existing:
        raise ProjectError("Invalid writer startup SQL")
    tokens = []
    pieces: list[str] = []
    statements: list[str] = []
    for match in _TOKEN.finditer(existing):
        token = match[0]
        if token.isspace():
            pieces.append(token)
            continue
        if token.startswith("--"):
            pieces.append(" ")
            continue
        if token.startswith("/*"):
            if "/*" in token[2:]:
                raise ProjectError("Nested startup comments are unsupported")
            pieces.append(" ")
            continue
        if token in {"'", '"'} or (
            token == "/" and existing[match.start() :].startswith("/*")
        ):
            raise ProjectError("Unterminated writer startup SQL")
        tokens.append(token)
        if token == ";":
            if "".join(pieces).strip():
                statements.append("".join(pieces).strip())
            pieces = []
        else:
            if token.startswith(("'", '"')) and ("\n" in token or "\r" in token):
                raise ProjectError("Multiline startup literals are unsupported")
            pieces.append(token)
    start = True
    for token in tokens:
        if token == ";":
            start = True
        elif start:
            if token.casefold() != "set":
                raise ProjectError("Writer startup must contain only SET statements")
            start = False
    if "".join(pieces).strip():
        statements.append("".join(pieces).strip())
    statements.append(f"set lockmode on {qualified} where level=mvcc, readlock=shared")
    # Ingres startup files require clean statement boundaries. Comments are not SQL
    # behavior; retain them in the original file, which this function never edits.
    return (
        ";\n".join(
            statement.replace("\r", " ").replace("\n", " ") for statement in statements
        )
        + "\n"
    )

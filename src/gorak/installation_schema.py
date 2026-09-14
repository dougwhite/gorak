"""Validate tracking column order, type, width, scale and nullability."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from .installation import FIELDS

COLUMN_SQL = """
select table_name, column_name, column_datatype, column_length,
       column_nulls, column_sequence, column_scale
from iicolumns where table_owner = '$ingres'
and table_name in ('gorak_tracking_install', 'gorak_change_events', 'gorak_journal_acks')
"""


@dataclass(frozen=True)
class Column:
    name: str
    datatype: str
    length: int
    nullable: bool = False


def expected_columns() -> dict[str, tuple[Column, ...]]:
    event = [
        Column("event_id", "integer", 8),
        Column("source_table", "varchar", 32),
        Column("action", "char", 1),
    ]
    for side in ("old", "new"):
        for name, kind in FIELDS.items():
            event.append(
                Column(
                    f"{side}_{name}",
                    "varchar" if kind.startswith("varchar") else "integer",
                    int(kind.removeprefix("varchar(").removesuffix(")"))
                    if kind.startswith("varchar")
                    else 4,
                    True,
                )
            )
    return {
        "gorak_tracking_install": (
            Column("schema_version", "integer", 4),
            Column("installation_id", "char", 36),
            Column("mode", "varchar", 32),
        ),
        "gorak_change_events": tuple(event),
        "gorak_journal_acks": (
            Column("consumer_id", "char", 36),
            Column("event_id", "integer", 8),
        ),
    }


def column_issues(
    connection: Any,
    present_tables: set[str],
    *,
    layouts: dict[str, tuple[Column, ...]] | None = None,
    query: str = COLUMN_SQL,
) -> list[str]:
    """Missing objects are reported by inventory; missing catalog rows fail closed."""
    expected = expected_columns() if layouts is None else layouts
    requested = present_tables & expected.keys()
    if not requested:
        return []
    actual: dict[str, list[tuple[int, Column, int]]] = {}
    try:
        for row in connection.execute(text(query)):
            table = str(row[0]).strip()
            nulls = str(row[4]).strip().upper()
            if nulls not in {"Y", "N"}:
                raise ValueError
            actual.setdefault(table, []).append(
                (
                    int(row[5]),
                    Column(
                        str(row[1]).strip(),
                        str(row[2]).strip().lower(),
                        int(row[3]),
                        nulls == "Y",
                    ),
                    int(row[6]),
                )
            )
    except (ValueError, TypeError, IndexError):
        return ["Invalid tracking column catalog metadata"]
    issues = []
    for table in sorted(requested):
        rows = sorted(actual.get(table, []), key=lambda row: row[0])
        target = [(i, column, 0) for i, column in enumerate(expected[table], 1)]
        if rows != target:
            issues.append(
                f"Missing or modified tracking column layout: {table} "
                "(check order, types, widths, scale and nullability)"
            )
    return issues

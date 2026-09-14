"""Read-only revision structure diagnostics; never certify fast-path eligibility."""

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .installation_check import CATALOG_QUERIES, check_installation
from .installation_definitions import assemble, canonical_sql
from .installation_schema import Column, column_issues
from .revision_installation import revision_installation_statements

LAYOUTS: dict[str, tuple[Column, ...]] = {
    "gorak_revision_install": (
        Column("schema_version", "integer", 4),
        Column("revision_id", "char", 36),
        Column("parent_installation_id", "char", 36),
    ),
    "gorak_revision_lanes": (
        Column("server_id", "varchar", 64),
        Column("session_id", "varchar", 64),
        Column("revision", "integer", 8),
    ),
}
COLUMN_SQL = """
select table_name, column_name, column_datatype, column_length,
       column_nulls, column_sequence, column_scale
from iicolumns where table_owner = '$ingres'
and table_name in ('gorak_revision_install', 'gorak_revision_lanes')
"""


@dataclass(frozen=True)
class RevisionCheck:
    status: str
    issues: list[str]
    revision_id: str | None = None
    parent_installation_id: str | None = None
    columns_verified: bool = False
    definitions_verified: bool = False
    incremental_ready: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def check_revision_installation(
    settings: OdbcSettings,
    engine_factory: EngineFactory = create_odbc_engine,
) -> RevisionCheck:
    """Check parent health, owner objects and generation; no event/lane scan.

    Separate connections and catalog queries are diagnostics, not an atomic
    certificate for concurrent DDL or a later source operation.
    """
    parent = check_installation(settings, engine_factory)
    issues = [f"Parent tracking: {issue}" for issue in parent.issues]
    if parent.schema_version != 2:
        issues.append("Revision extension requires parent tracking schema 2")
    engine = engine_factory(settings)
    revision_id = None
    try:
        with engine.connect() as connection:
            connection.execute(
                text("set lockmode session where readlock=shared, timeout=5")
            )
            tables = {
                str(row[0]).strip()
                for row in connection.execute(text(CATALOG_QUERIES["tables"]))
            }
            rules = {
                (str(row[0]).strip(), str(row[1]).strip())
                for row in connection.execute(text(CATALOG_QUERIES["rules"]))
            }
            procedures = {
                str(row[0]).strip()
                for row in connection.execute(text(CATALOG_QUERIES["procedures"]))
            }
            issues.extend(
                f"Missing owner table: {name}"
                for name in sorted(LAYOUTS.keys() - tables)
            )
            columns = column_issues(
                connection, tables, layouts=LAYOUTS, query=COLUMN_SQL
            )
            issues.extend(columns)
            columns_verified = LAYOUTS.keys() <= tables and not columns
            definitions = []
            for kind, name, present, catalog, owner in (
                (
                    "rule",
                    "gorak_revision_capture",
                    ("gorak_revision_capture", "gorak_change_events") in rules,
                    "iirules",
                    "rule",
                ),
                (
                    "procedure",
                    "gorak_bump_revision",
                    "gorak_bump_revision" in procedures,
                    "iiprocedures",
                    "procedure",
                ),
            ):
                if not present:
                    definitions.append(f"Missing or wrong-target owner {kind}: {name}")
                    continue
                rows = connection.execute(
                    text(
                        f"select text_sequence, text_segment from {catalog} "
                        f"where {owner}_owner = '$ingres' and {owner}_name = '{name}'"
                    )
                )
                try:
                    actual = assemble([(int(row[0]), str(row[1])) for row in rows])
                except (TypeError, ValueError, IndexError):
                    actual = None
                expected = next(
                    s
                    for s in revision_installation_statements()
                    if s.startswith(f"create {kind} ")
                )
                if actual is None or canonical_sql(actual) != canonical_sql(expected):
                    definitions.append(
                        f"Missing or modified revision {kind} definition: {name}"
                    )
            issues.extend(definitions)
            if columns_verified:
                # Ingres forbids changing lock level after catalog reads in a
                # transaction. End that read-only phase before configuring MVCC.
                connection.rollback()
                connection.execute(
                    text(
                        'set lockmode on "$ingres".gorak_revision_install '
                        "where level=mvcc, readlock=shared, timeout=5"
                    )
                )
                result = connection.execute(
                    text(
                        "select first 2 schema_version, revision_id, parent_installation_id "
                        'from "$ingres".gorak_revision_install'
                    )
                )
                try:
                    rows = result.fetchmany(2)
                finally:
                    result.close()
                try:
                    if len(rows) != 1 or rows[0][0] != 1:
                        raise ValueError
                    identity = UUID(str(rows[0][1]).strip())
                    binding = UUID(str(rows[0][2]).strip())
                    if (
                        not identity.int
                        or not binding.int
                        or str(binding) != parent.installation_id
                    ):
                        raise ValueError
                    revision_id = str(identity)
                except (TypeError, ValueError, IndexError):
                    issues.append("Invalid revision generation or parent binding")
    finally:
        engine.dispose()
    return RevisionCheck(
        "incomplete" if issues else "revision_structure_verified",
        issues,
        revision_id,
        parent.installation_id,
        columns_verified,
        not definitions,
    )

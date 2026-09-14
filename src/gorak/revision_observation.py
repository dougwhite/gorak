"""Bounded experimental counter samples, not certified source checkpoints."""

from dataclasses import dataclass

from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .project import ProjectError
from .writer_init import counter_table_name


@dataclass(frozen=True)
class RevisionSample:
    # None deliberately prevents a truncated sample from becoming a reusable token.
    lanes: tuple[tuple[str, str, int], ...] | None
    scanned_rows: int

    @property
    def complete(self) -> bool:
        return self.lanes is not None


def observe_revisions(
    settings: OdbcSettings,
    table: str,
    limit: int = 4096,
    engine_factory: EngineFactory = create_odbc_engine,
) -> RevisionSample:
    """Read at most limit+1 committed rows from one owner-table query.

    The caller must verify schema, database generation and capture coverage before
    using a sample. No installation, acknowledgment or source operation is performed.
    Equal samples alone do not certify restore continuity or history retention.
    """
    qualified = counter_table_name(table)
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ProjectError("Revision observation budget must be between 1 and 100000")
    engine = engine_factory(settings)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    f"set lockmode on {qualified} where level=mvcc, readlock=shared, timeout=5"
                )
            )
            result = connection.execute(
                text(
                    f"select first {limit + 1} server_id, session_id, revision from {qualified}"
                )
            )
            lanes: dict[tuple[str, str], int] = {}
            scanned = 0
            try:
                while scanned <= limit:
                    rows = result.fetchmany(min(256, limit + 1 - scanned))
                    if not rows:
                        break
                    for row in rows:
                        if len(row) != 3:
                            raise ProjectError("Invalid revision counter row")
                        server, session, revision = row
                        if (
                            not isinstance(server, str)
                            or not isinstance(session, str)
                            or not 1 <= len(server.strip()) <= 64
                            or not 1 <= len(session.strip()) <= 64
                            or type(revision) is not int
                            or not 1 <= revision <= 9223372036854775807
                        ):
                            raise ProjectError("Invalid revision counter row")
                        key = (server.strip(), session.strip())
                        if key in lanes:
                            raise ProjectError("Duplicate revision counter identity")
                        lanes[key] = revision
                        scanned += 1
            finally:
                result.close()
            if scanned > limit:
                return RevisionSample(None, scanned)
            return RevisionSample(
                tuple(sorted((*key, value) for key, value in lanes.items())), scanned
            )
    finally:
        engine.dispose()

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


@dataclass(frozen=True)
class BoundRevisionSample:
    revision_id: str
    parent_installation_id: str
    sample: RevisionSample


def observe_installed_revisions(
    settings: OdbcSettings,
    limit: int = 4096,
    engine_factory: EngineFactory = create_odbc_engine,
) -> BoundRevisionSample:
    """Bind a diagnostic sample to extension and parent identities in one statement.

    This verifies marker consistency, not stored capture definitions or restore
    continuity. Consumers must retain full-reference verification.
    """
    from uuid import UUID

    from .revision_installation import REVISION_TABLE

    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ProjectError("Revision observation budget must be between 1 and 100000")
    engine = engine_factory(settings)
    try:
        with engine.connect() as connection:
            for table in (
                "gorak_revision_install",
                "gorak_tracking_install",
                REVISION_TABLE,
            ):
                connection.execute(
                    text(
                        f"set lockmode on {counter_table_name(table)} where level=mvcc, readlock=shared, timeout=5"
                    )
                )
            result = connection.execute(
                text(f"""
select first {limit + 1} m.schema_version,m.revision_id,m.parent_installation_id,
 p.schema_version,p.installation_id,p.mode,
 (select count(*) from "$ingres".gorak_revision_install),
 (select count(*) from "$ingres".gorak_tracking_install),
 l.server_id,l.session_id,l.revision
from "$ingres".gorak_revision_install m
cross join "$ingres".gorak_tracking_install p
left join "$ingres".{REVISION_TABLE} l on 1=1
""")
            )
            binding: tuple[str, str] | None = None
            lanes: dict[tuple[str, str], int] = {}
            scanned = 0
            empty = False
            try:
                while scanned <= limit:
                    rows = result.fetchmany(min(256, limit + 1 - scanned))
                    if not rows:
                        break
                    for row in rows:
                        if len(row) != 11:
                            raise ValueError
                        (
                            version,
                            revision_id,
                            parent,
                            parent_version,
                            actual_parent,
                            mode,
                            marker_count,
                            parent_count,
                            server,
                            session,
                            revision,
                        ) = row
                        revision_id, parent, actual_parent = (
                            UUID(str(v).strip())
                            for v in (revision_id, parent, actual_parent)
                        )
                        if (
                            version != 1
                            or parent_version != 2
                            or str(mode).strip() != "capture_only"
                            or marker_count != 1
                            or parent_count != 1
                            or not revision_id.int
                            or not parent.int
                            or parent != actual_parent
                        ):
                            raise ValueError
                        current = (str(revision_id), str(parent))
                        if binding is not None and binding != current:
                            raise ValueError
                        binding = current
                        if server is None and session is None and revision is None:
                            if empty or lanes:
                                raise ValueError
                            empty = True
                            # The left join returns exactly one row for an empty table.
                            continue
                        if (
                            empty
                            or not isinstance(server, str)
                            or not isinstance(session, str)
                        ):
                            raise ValueError
                        key = (server.strip(), session.strip())
                        if (
                            not all(1 <= len(value) <= 64 for value in key)
                            or key in lanes
                            or type(revision) is not int
                            or not 1 <= revision <= 9223372036854775807
                        ):
                            raise ValueError
                        lanes[key] = revision
                        scanned += 1
            finally:
                result.close()
            if binding is None:
                raise ValueError
            sample = RevisionSample(
                None
                if scanned > limit
                else tuple(sorted((*key, value) for key, value in lanes.items())),
                scanned,
            )
            return BoundRevisionSample(*binding, sample)
    except (ValueError, TypeError) as ex:
        raise ProjectError(
            "Invalid revision installation binding or counter data; full verification required"
        ) from ex
    finally:
        engine.dispose()

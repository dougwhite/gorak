"""Transactional direct ODBC restoration into an empty source database only."""

from dataclasses import dataclass

from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .encoded_graph import UnsupportedSource
from .storage_archive import TABLE_COLUMNS, Archive
from .storage_capture import _Reader


@dataclass(frozen=True)
class RestoreResult:
    applications: int
    components: int
    entities: int
    dry_run: bool


def restore(
    settings: OdbcSettings,
    archive: Archive,
    *,
    dry_run: bool = False,
    engine_factory: EngineFactory = create_odbc_engine,
) -> RestoreResult:
    """Refuse existing source under transaction-held locks; rollback any failure.

    This is a fresh database operation, not an update/push conflict-check bypass.
    Source rows remain out of date for compilation after the successful commit.
    """
    archive.validate()
    result = RestoreResult(
        len(archive.tables["ii_applications"]),
        len(archive.tables["ii_components"]),
        len(archive.tables["ii_entities"]),
        dry_run,
    )
    engine = engine_factory(settings)
    try:
        with engine.begin() as connection:
            connection.execute(text("set session isolation level serializable"))
            connection.execute(
                text(
                    "set lockmode session where level=table,readlock=exclusive,timeout=5"
                )
            )
            reader = _Reader(connection)
            # Respect native allocator locking before acquiring source table locks.
            allocator = reader.rows('select object_id from "$ingres".ii_id')
            if len(allocator) != 1 or type(allocator[0]["object_id"]) is not int:
                raise UnsupportedSource("invalid_source_identity_allocator")
            floor = allocator[0]["object_id"]
            assert isinstance(floor, int)
            if floor < 0 or floor + result.entities >= 2**31:
                raise UnsupportedSource("source_identity_allocator_exhausted")
            for table, columns in TABLE_COLUMNS.items():
                cursor = connection.execute(
                    text('select * from "$ingres".' + table + " where 1=0")
                )
                try:
                    if list(cursor.keys()) != columns.split():
                        raise UnsupportedSource("source_destination_schema_mismatch")
                finally:
                    cursor.close()
                rows = reader.rows(
                    'select count(*) as row_count from "$ingres".' + table
                )
                if rows != [{"row_count": 0}]:
                    raise UnsupportedSource("source_restore_requires_empty_database")
            # Other stored objects/locks are not portable source in this archive.
            for table in (
                "ii_encodings",
                "ii_stored_strings",
                "ii_stored_nstrings",
                "ii_stored_bitmaps",
                "ii_locks",
            ):
                rows = reader.rows(
                    'select count(*) as row_count from "$ingres".' + table
                )
                if rows != [{"row_count": 0}]:
                    raise UnsupportedSource(
                        "source_restore_requires_empty_auxiliary_storage"
                    )
            if dry_run:
                return result
            identities = sorted(
                int(str(row["entity_id"])) for row in archive.tables["ii_entities"]
            )
            mapped = archive.remap(
                {value: floor + index + 1 for index, value in enumerate(identities)}
            )
            # Never advertise captured compiler artifacts as freshly compiled here.
            for row in mapped.tables["ii_components"]:
                row["current_make"] = 0
            connection.execute(
                text('update "$ingres".ii_id set object_id=:value'),
                {"value": floor + result.entities},
            )
            for table, columns in TABLE_COLUMNS.items():
                keys = columns.split()
                statement = text(
                    'insert into "$ingres".'
                    + table
                    + " ("
                    + ",".join(keys)
                    + ") values ("
                    + ",".join(":" + key for key in keys)
                    + ")"
                )
                rows = mapped.tables[table]
                for start in range(0, len(rows), 100):
                    connection.execute(statement, rows[start : start + 100])
            # Verify stored values within the same transaction, before publication.
            actual = Archive(
                {
                    table: reader.rows('select * from "$ingres".' + table)
                    for table in TABLE_COLUMNS
                }
            )
            if reader.rows('select object_id from "$ingres".ii_id') != [
                {"object_id": floor + result.entities}
            ]:
                raise UnsupportedSource("source_allocator_readback_mismatch")
            if actual.dumps() != mapped.dumps():
                raise UnsupportedSource("source_restore_readback_mismatch")
        return result
    finally:
        engine.dispose()

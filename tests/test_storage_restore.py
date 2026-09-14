from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from gorak.database import OdbcSettings
from gorak.encoded_graph import UnsupportedSource
from gorak.storage_archive import INTEGER_COLUMNS, TABLE_COLUMNS, Archive
from gorak.storage_restore import restore
from tests.test_storage_archive import archive

SETTINGS = OdbcSettings("driver", "host", "port", "database", "user", "password")


class Backend:
    """Real transactional SQLite rows; only Ingres locking statements are recorded."""

    def __init__(self, path: Path):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as c:
            c.execute(text('attach database :path as "$ingres"'), {"path": str(path)})
            for table, columns in TABLE_COLUMNS.items():
                layout = ",".join(
                    key + (" integer" if key in INTEGER_COLUMNS[table] else " text")
                    for key in columns.split()
                )
                c.execute(text('create table "$ingres".' + table + " (" + layout + ")"))
            c.execute(text('create table "$ingres".ii_id (object_id integer)'))
            c.execute(text('insert into "$ingres".ii_id values (10000)'))
            for name in [
                "ii_encodings",
                "ii_stored_strings",
                "ii_stored_nstrings",
                "ii_stored_bitmaps",
                "ii_locks",
            ]:
                c.execute(text('create table "$ingres".' + name + " (id integer)"))
        self.settings: list[str] = []
        self.fail_table: str | None = None
        self.corrupt_readback = False
        self.skip_allocator = False
        self.disposed = 0

    @contextmanager
    def begin(self) -> Iterator[Any]:
        with self.engine.begin() as c:
            yield self.wrap(c)

    @contextmanager
    def connect(self) -> Iterator[Any]:
        with self.engine.connect() as c:
            yield self.wrap(c)

    def wrap(self, connection: Any) -> Any:
        backend = self

        class Wrapped:
            def execute(self, statement: Any, parameters: Any = None) -> Any:
                query = str(statement)
                if query.startswith("set "):
                    backend.settings.append(query)
                    return None
                if backend.fail_table and query.startswith(
                    'insert into "$ingres".' + backend.fail_table
                ):
                    raise RuntimeError("injected storage failure")
                if backend.skip_allocator and query.startswith(
                    'update "$ingres".ii_id'
                ):
                    return None
                result = connection.execute(statement, parameters or {})
                if backend.corrupt_readback and query.startswith(
                    'insert into "$ingres".ii_components'
                ):
                    connection.execute(
                        text('update "$ingres".ii_components set alter_count=999')
                    )
                return result

        return Wrapped()

    def dispose(self) -> None:
        self.disposed += 1

    def rows(self, table: str) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [
                dict(r)
                for r in c.execute(text('select * from "$ingres".' + table)).mappings()
            ]

    def seed(self, source: Archive) -> None:
        with self.engine.begin() as c:
            for table, columns in TABLE_COLUMNS.items():
                keys = columns.split()
                if source.tables[table]:
                    c.execute(
                        text(
                            'insert into "$ingres".'
                            + table
                            + " ("
                            + ",".join(keys)
                            + ") values ("
                            + ",".join(":" + k for k in keys)
                            + ")"
                        ),
                        source.tables[table],
                    )


def test_restore_commits_remapped_rows_and_invalidates_compilation(
    tmp_path: Path,
) -> None:
    backend = Backend(tmp_path / "target.sqlite")
    source = archive()
    source.tables["ii_components"][0]["current_make"] = 3
    result = restore(SETTINGS, source, engine_factory=lambda _: backend)
    assert result.entities == 4 and not result.dry_run
    assert backend.rows("ii_id") == [{"object_id": 10004}]
    assert backend.rows("ii_components")[0]["entity_id"] == 10004
    assert backend.rows("ii_components")[0]["current_make"] == 0
    assert source.tables["ii_components"][0]["current_make"] == 3
    assert any("readlock=exclusive" in s for s in backend.settings)
    assert backend.disposed == 1


def test_dry_run_checks_target_without_allocating_or_writing(tmp_path: Path) -> None:
    backend = Backend(tmp_path / "target.sqlite")
    assert restore(
        SETTINGS, archive(), dry_run=True, engine_factory=lambda _: backend
    ).dry_run
    assert backend.rows("ii_id") == [{"object_id": 10000}]
    assert backend.rows("ii_entities") == []


def test_existing_source_is_never_replaced(tmp_path: Path) -> None:
    backend = Backend(tmp_path / "target.sqlite")
    backend.seed(archive())
    before = backend.rows("ii_entities")
    with pytest.raises(UnsupportedSource, match="empty_database"):
        restore(SETTINGS, archive(), engine_factory=lambda _: backend)
    assert backend.rows("ii_entities") == before
    assert backend.rows("ii_id") == [{"object_id": 10000}]


@pytest.mark.parametrize("failure", ["insert", "readback", "allocator"])
def test_any_failure_rolls_back_source_and_allocator(
    tmp_path: Path, failure: str
) -> None:
    backend = Backend(tmp_path / "target.sqlite")
    if failure == "insert":
        backend.fail_table = "ii_srcobj_encoded"
    elif failure == "readback":
        backend.corrupt_readback = True
    else:
        backend.skip_allocator = True
    with pytest.raises((RuntimeError, UnsupportedSource)):
        restore(SETTINGS, archive(), engine_factory=lambda _: backend)
    assert all(backend.rows(table) == [] for table in TABLE_COLUMNS)
    assert backend.rows("ii_id") == [{"object_id": 10000}]
    assert backend.disposed == 1


def test_rejects_existing_auxiliary_storage(tmp_path: Path) -> None:
    backend = Backend(tmp_path / "target.sqlite")
    with backend.engine.begin() as c:
        c.execute(text('insert into "$ingres".ii_stored_strings values (1)'))
    with pytest.raises(UnsupportedSource, match="auxiliary_storage"):
        restore(SETTINGS, archive(), engine_factory=lambda _: backend)
    assert backend.rows("ii_entities") == []

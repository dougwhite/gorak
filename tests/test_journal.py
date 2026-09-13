import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from gorak.database import OdbcSettings
from gorak.installation import FIELDS
from gorak.journal import (
    EVENT_SQL,
    MARKER_SQL,
    JournalEvent,
    acknowledgment_store,
    consume_journal,
    poll_journal,
)
from gorak.project import ProjectError

SETTINGS = OdbcSettings("driver", "host", "port", "source_db", "user", "secret")


def event(number: int) -> tuple[Any, ...]:
    # A deletion must retain the original identity and name.
    values: list[Any] = [None] * (2 * len(FIELDS))
    values[0] = 123
    values[list(FIELDS).index("object_name")] = "deleted_component "
    return (number, "ii_entities ", "d ", *values)


class Database:
    def __init__(self) -> None:
        self.identity = str(uuid4())
        self.events = [event(3)]
        self.engine = MagicMock()
        self.connection = self.engine.connect.return_value.__enter__.return_value
        self.connection.execute.side_effect = self.execute

    def execute(self, query: Any) -> Any:
        if str(query) == MARKER_SQL:
            return [(1, self.identity, "capture_only")]
        if str(query) == EVENT_SQL:
            cursor = MagicMock()
            remaining = list(self.events)

            def fetchmany(count: int) -> list[tuple[Any, ...]]:
                chunk = remaining[:count]
                del remaining[:count]
                return chunk

            cursor.fetchmany.side_effect = fetchmany
            return cursor
        return []

    def factory(self, settings: OdbcSettings) -> Any:
        return self.engine


def test_late_lower_commit_is_not_skipped_and_other_checkout_is_independent(
    tmp_path: Path,
) -> None:
    db = Database()
    processed: list[int] = []
    with acknowledgment_store(tmp_path / "a.sqlite3") as store:
        consume_journal(
            SETTINGS,
            store,
            lambda e: processed.append(e.event_id),
            engine_factory=db.factory,
        )
        db.events = [event(2), event(3)]
        batch = consume_journal(
            SETTINGS,
            store,
            lambda e: processed.append(e.event_id),
            engine_factory=db.factory,
        )
        assert [e.event_id for e in batch.events] == [2]
        assert processed == [3, 2]
        assert not poll_journal(SETTINGS, store, engine_factory=db.factory).events
    with acknowledgment_store(tmp_path / "b.sqlite3") as other:
        assert len(poll_journal(SETTINGS, other, engine_factory=db.factory).events) == 2


def test_callback_failure_replays_only_unacknowledged_work_after_reopen(
    tmp_path: Path,
) -> None:
    db = Database()
    db.events = [event(1), event(2)]
    path = tmp_path / "ack.sqlite3"

    def process(item: JournalEvent) -> None:
        if item.event_id == 2:
            raise RuntimeError("interrupted")

    with acknowledgment_store(path) as store:
        with pytest.raises(RuntimeError, match="interrupted"):
            consume_journal(SETTINGS, store, process, engine_factory=db.factory)
    with acknowledgment_store(path) as store:
        assert [
            e.event_id
            for e in poll_journal(SETTINGS, store, engine_factory=db.factory).events
        ] == [2]


def test_preview_does_not_acknowledge_and_preserves_tombstone(tmp_path: Path) -> None:
    db = Database()
    with acknowledgment_store(tmp_path / "ack.sqlite3") as store:
        first = poll_journal(SETTINGS, store, engine_factory=db.factory)
        assert first == poll_journal(SETTINGS, store, engine_factory=db.factory)
        assert first.events[0].old["object_name"] == "deleted_component"
        assert first.events[0].old["object_id"] == 123
        assert first.events[0].new["object_id"] is None
        assert store.execute("select count(*) from acknowledged").fetchone() == (0,)


def test_changed_installation_stops_before_source_read(tmp_path: Path) -> None:
    db = Database()
    with acknowledgment_store(tmp_path / "ack.sqlite3") as store:
        poll_journal(SETTINGS, store, engine_factory=db.factory)
        db.identity = str(uuid4())
        db.connection.execute.reset_mock()
        with pytest.raises(ProjectError, match="rebootstrap"):
            poll_journal(SETTINGS, store, engine_factory=db.factory)
        assert not any(
            str(c.args[0]) == EVENT_SQL for c in db.connection.execute.call_args_list
        )


def test_limit_applies_to_pending_events_after_acknowledged_rows(
    tmp_path: Path,
) -> None:
    db = Database()
    with acknowledgment_store(tmp_path / "ack.sqlite3") as store:
        consume_journal(SETTINGS, store, lambda e: None, engine_factory=db.factory)
        db.events = [event(3), event(4), event(5)]
        batch = poll_journal(SETTINGS, store, limit=1, engine_factory=db.factory)
        assert [e.event_id for e in batch.events] == [4]
        assert batch.scanned_events == 2
    sql = [str(c.args[0]) for c in db.connection.execute.call_args_list]
    assert any("level = mvcc, readlock = shared" in q for q in sql)
    assert not any("event_id >" in q for q in sql)


def test_acknowledgment_failure_replays_completed_callback(tmp_path: Path) -> None:
    db = Database()
    with acknowledgment_store(tmp_path / "ack.sqlite3") as store:
        poll_journal(SETTINGS, store, engine_factory=db.factory)
        store.execute(
            "create trigger fail_ack before insert on acknowledged begin select raise(abort, 'disk failure'); end"
        )
        processed: list[int] = []
        with pytest.raises(sqlite3.IntegrityError):
            consume_journal(
                SETTINGS,
                store,
                lambda e: processed.append(e.event_id),
                engine_factory=db.factory,
            )
        assert processed == [3]
        assert len(poll_journal(SETTINGS, store, engine_factory=db.factory).events) == 1


def test_query_failure_disposes_without_acknowledgment(tmp_path: Path) -> None:
    db = Database()
    db.connection.execute.side_effect = RuntimeError("MVCC unavailable")
    with acknowledgment_store(tmp_path / "ack.sqlite3") as store:
        with pytest.raises(RuntimeError, match="MVCC unavailable"):
            poll_journal(SETTINGS, store, engine_factory=db.factory)
        assert store.execute("select count(*) from acknowledged").fetchone() == (0,)
    db.engine.dispose.assert_called_once()


@pytest.mark.parametrize("limit", [0, -1, 10001])
def test_invalid_limit_never_connects(tmp_path: Path, limit: int) -> None:
    db = Database()
    with acknowledgment_store(tmp_path / "ack.sqlite3") as store:
        with pytest.raises(ProjectError, match="limit"):
            poll_journal(SETTINGS, store, limit, db.factory)
    db.engine.connect.assert_not_called()


def test_malformed_event_does_not_advance_progress(tmp_path: Path) -> None:
    db = Database()
    db.events = [("not-an-id", *event(3)[1:])]
    with acknowledgment_store(tmp_path / "ack.sqlite3") as store:
        with pytest.raises(ProjectError, match="Invalid source journal data"):
            consume_journal(SETTINGS, store, lambda e: None, engine_factory=db.factory)
        assert store.execute("select count(*) from acknowledged").fetchone() == (0,)


@pytest.mark.parametrize("count,complete", [(0, True), (1, True), (2, False)])
def test_legacy_pending_completeness_without_acknowledgment(
    tmp_path: Path,
    count: int,
    complete: bool,
) -> None:
    db = Database()
    db.events = [event(i) for i in range(1, count + 1)]
    with acknowledgment_store(tmp_path / "ack.sqlite3") as store:
        batch = poll_journal(SETTINGS, store, 1, db.factory, verify_complete=True)
        assert batch.complete is complete
        assert len(batch.events) == min(count, 1)
        assert store.execute("select count(*) from acknowledged").fetchone() == (0,)


def test_lookahead_skips_legacy_acknowledged_rows(tmp_path: Path) -> None:
    db = Database()
    db.events = [event(1), event(2), event(3)]
    with acknowledgment_store(tmp_path / "ack.sqlite3") as store:
        store.execute("insert into acknowledged values (2)")
        store.commit()
        batch = poll_journal(SETTINGS, store, 1, db.factory, verify_complete=True)
        assert batch.complete is False
        assert [e.event_id for e in batch.events] == [1]
        assert batch.scanned_events == 3


def test_malformed_lookahead_is_not_silently_ignored(tmp_path: Path) -> None:
    db = Database()
    db.events = [event(1), ("bad-id", *event(2)[1:])]
    with acknowledgment_store(tmp_path / "ack.sqlite3") as store:
        with pytest.raises(ProjectError, match="Invalid source journal data"):
            poll_journal(SETTINGS, store, 1, db.factory, verify_complete=True)
        assert store.execute("select count(*) from acknowledged").fetchone() == (0,)

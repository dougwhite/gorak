import re
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from gorak.database import OdbcSettings
from gorak.installation import FIELDS
from gorak.journal import acknowledgment_store, consume_journal, poll_journal
from gorak.journal_server import consumer_identity

SETTINGS = OdbcSettings("driver", "host", "port", "source_db", "user", "secret")


class Server:
    """Execute production anti-join/ack SQL against SQLite with FIRST translated."""

    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute('attach database ":memory:" as "$ingres"')
        self.db.execute(
            'create table "$ingres".gorak_tracking_install (schema_version, installation_id, mode)'
        )
        self.db.execute(
            'insert into "$ingres".gorak_tracking_install values (2, ?, "capture_only")',
            (str(uuid4()),),
        )
        columns = ", ".join(
            f"{side}_{name}" for side in ("old", "new") for name in FIELDS
        )
        self.db.execute(
            f'create table "$ingres".gorak_change_events (event_id integer primary key, source_table, action, {columns})'
        )
        self.db.execute(
            'create table "$ingres".gorak_journal_acks (consumer_id, event_id, primary key(consumer_id,event_id))'
        )
        self.db.commit()
        self.connection = MagicMock()
        self.connection.execute.side_effect = self.execute
        self.connection.commit.side_effect = self.db.commit
        self.engine = MagicMock()
        self.engine.connect.return_value.__enter__.return_value = self.connection

    def execute(self, statement: Any, params: Any = None) -> Any:
        sql = str(statement)
        if sql.startswith("set lockmode"):
            return []
        match = re.match(r"select first (\d+) ", sql)
        if match:
            sql = "select " + sql[match.end() :] + " limit " + match[1]
        return self.db.execute(sql, params or {})

    def factory(self, settings: OdbcSettings) -> Any:
        return self.engine

    def add(self, event_id: int) -> None:
        self.db.execute(
            'insert into "$ingres".gorak_change_events (event_id, source_table, action) values (?, "ii_entities", "u")',
            (event_id,),
        )
        self.db.commit()


def test_pending_query_excludes_acks_but_keeps_late_lower_commit(
    tmp_path: Path,
) -> None:
    server = Server()
    server.add(3)
    with acknowledgment_store(tmp_path / "a.sqlite3") as store:
        consume_journal(SETTINGS, store, lambda e: None, engine_factory=server.factory)
        server.add(2)
        batch = poll_journal(SETTINGS, store, engine_factory=server.factory)
        assert [e.event_id for e in batch.events] == [2]
        assert batch.scanned_events == 1
    with acknowledgment_store(tmp_path / "b.sqlite3") as store:
        assert (
            len(poll_journal(SETTINGS, store, engine_factory=server.factory).events)
            == 2
        )


def test_empty_poll_transfers_no_acknowledged_events(tmp_path: Path) -> None:
    server = Server()
    for i in range(1, 20):
        server.add(i)
    with acknowledgment_store(tmp_path / "a.sqlite3") as store:
        consume_journal(SETTINGS, store, lambda e: None, engine_factory=server.factory)
        batch = poll_journal(SETTINGS, store, engine_factory=server.factory)
        assert batch.scanned_events == 0
        assert not batch.events
        assert store.execute("select count(*) from published").fetchone() == (19,)


def test_uncertain_server_commit_retries_without_losing_events(tmp_path: Path) -> None:
    server = Server()
    server.add(1)

    def uncertain_commit() -> None:
        server.db.commit()
        raise RuntimeError("connection lost after commit")

    with acknowledgment_store(tmp_path / "a.sqlite3") as store:
        consume_journal(SETTINGS, store, lambda e: None, engine_factory=server.factory)
        server.connection.commit.side_effect = uncertain_commit
        with pytest.raises(RuntimeError, match="connection lost"):
            poll_journal(SETTINGS, store, engine_factory=server.factory)
        assert store.execute("select count(*) from published").fetchone() == (0,)
        server.connection.commit.side_effect = server.db.commit
        assert not poll_journal(SETTINGS, store, engine_factory=server.factory).events
        assert store.execute("select count(*) from published").fetchone() == (1,)


def test_legacy_local_acknowledgments_publish_and_identity_persists(
    tmp_path: Path,
) -> None:
    server = Server()
    server.add(1)
    path = tmp_path / "a.sqlite3"
    with acknowledgment_store(path) as store:
        # v1 consumer already completed this event.
        store.execute("insert into acknowledged values (1)")
        store.commit()
        identity = consumer_identity(store)
        assert not poll_journal(SETTINGS, store, engine_factory=server.factory).events
    with acknowledgment_store(path) as store:
        assert consumer_identity(store) == identity


def test_limit_is_applied_by_server_and_preview_does_not_ack(tmp_path: Path) -> None:
    server = Server()
    for i in range(1, 4):
        server.add(i)
    with acknowledgment_store(tmp_path / "a.sqlite3") as store:
        first = poll_journal(SETTINGS, store, limit=1, engine_factory=server.factory)
        assert len(first.events) == 1
        assert first == poll_journal(
            SETTINGS, store, limit=1, engine_factory=server.factory
        )
        assert server.db.execute(
            'select count(*) from "$ingres".gorak_journal_acks'
        ).fetchone() == (0,)


def test_outbox_failure_rolls_back_local_acknowledgment(tmp_path: Path) -> None:
    server = Server()
    server.add(1)
    with acknowledgment_store(tmp_path / "a.sqlite3") as store:
        poll_journal(SETTINGS, store, engine_factory=server.factory)
        store.execute(
            "create trigger fail_outbox before insert on ack_outbox begin select raise(abort, 'storage failure'); end"
        )
        with pytest.raises(sqlite3.IntegrityError):
            consume_journal(
                SETTINGS, store, lambda e: None, engine_factory=server.factory
            )
        assert store.execute("select count(*) from acknowledged").fetchone() == (0,)
        assert (
            len(poll_journal(SETTINGS, store, engine_factory=server.factory).events)
            == 1
        )


@pytest.mark.parametrize(
    "count,complete", [(0, True), (1, True), (2, False), (3, False)]
)
def test_server_completeness_reads_at_most_one_extra_event(
    tmp_path: Path,
    count: int,
    complete: bool,
) -> None:
    server = Server()
    for i in range(1, count + 1):
        server.add(i)
    with acknowledgment_store(tmp_path / "a.sqlite3") as store:
        batch = poll_journal(SETTINGS, store, 1, server.factory, verify_complete=True)
        assert batch.complete is complete
        assert batch.scanned_events == min(count, 2)
        assert len(batch.events) == min(count, 1)
        assert store.execute("select count(*) from acknowledged").fetchone() == (0,)
        assert server.db.execute(
            'select count(*) from "$ingres".gorak_journal_acks'
        ).fetchone() == (0,)
        sql = [str(call.args[0]) for call in server.connection.execute.call_args_list]
        assert any(query.startswith("select first 2 ") for query in sql)


def test_late_commit_remains_visible_after_complete_query(tmp_path: Path) -> None:
    server = Server()
    server.add(20)
    with acknowledgment_store(tmp_path / "a.sqlite3") as store:
        first = poll_journal(SETTINGS, store, 1, server.factory, verify_complete=True)
        assert first.complete is True
        server.add(10)
        later = poll_journal(SETTINGS, store, 1, server.factory, verify_complete=True)
        assert later.complete is False
        assert store.execute("select count(*) from acknowledged").fetchone() == (0,)


@pytest.mark.parametrize("count,complete", [(5, True), (6, True), (7, False)])
def test_pending_window_spans_chunks_without_acknowledging(
    tmp_path: Path, count: int, complete: bool
) -> None:
    server = Server()
    for identity in range(1, count + 1):
        server.add(identity)
    with acknowledgment_store(tmp_path / "window.sqlite3") as store:
        batch = poll_journal(
            SETTINGS,
            store,
            limit=2,
            engine_factory=server.factory,
            verify_complete=True,
            max_pending=6,
        )
        assert len(batch.events) == min(count, 6)
        assert batch.complete is complete
        assert batch.scanned_events == count
        assert store.execute("select count(*) from acknowledged").fetchone() == (0,)
        assert server.db.execute(
            'select count(*) from "$ingres".gorak_journal_acks'
        ).fetchone() == (0,)
        assert (
            poll_journal(
                SETTINGS,
                store,
                limit=2,
                engine_factory=server.factory,
                verify_complete=True,
                max_pending=6,
            )
            == batch
        )


def test_invalid_later_chunk_discards_entire_window(tmp_path: Path) -> None:
    from gorak.project import ProjectError

    server = Server()
    for identity in range(1, 6):
        server.add(identity)
    server.db.execute(
        'update "$ingres".gorak_change_events set action="bad" where event_id=5'
    )
    with acknowledgment_store(tmp_path / "window.sqlite3") as store:
        with pytest.raises(ProjectError, match="Invalid source journal event"):
            poll_journal(
                SETTINGS,
                store,
                limit=2,
                engine_factory=server.factory,
                verify_complete=True,
                max_pending=6,
            )
        assert store.execute("select count(*) from acknowledged").fetchone() == (0,)
        server.db.execute(
            'update "$ingres".gorak_change_events set action="u" where event_id=5'
        )
        assert (
            len(
                poll_journal(
                    SETTINGS,
                    store,
                    limit=2,
                    engine_factory=server.factory,
                    verify_complete=True,
                    max_pending=6,
                ).events
            )
            == 5
        )


@pytest.mark.parametrize("budget", [1, 100001])
def test_pending_window_rejects_invalid_budget(tmp_path: Path, budget: int) -> None:
    from gorak.project import ProjectError

    with acknowledgment_store(tmp_path / "window.sqlite3") as store:
        with pytest.raises(ProjectError, match="Pending window"):
            poll_journal(
                SETTINGS, store, limit=2, verify_complete=True, max_pending=budget
            )


def test_pending_window_does_not_skip_lower_id_committed_after_checkpoint(
    tmp_path: Path,
) -> None:
    from gorak.journal_observer import checkpoint_observer

    server = Server()
    for identity in (2, 3, 4, 5, 6):
        server.add(identity)
    path = tmp_path / "window.sqlite3"
    with acknowledgment_store(path) as store:
        batch = poll_journal(
            SETTINGS,
            store,
            limit=2,
            engine_factory=server.factory,
            verify_complete=True,
            max_pending=6,
        )
        assert batch.complete is True
    checkpoint_observer(path, batch.events)
    server.add(1)
    with acknowledgment_store(path) as store:
        later = poll_journal(
            SETTINGS,
            store,
            limit=2,
            engine_factory=server.factory,
            verify_complete=True,
            verify_receipts=True,
            max_pending=6,
        )
        assert [event.event_id for event in later.events] == [1]
        assert later.complete is True

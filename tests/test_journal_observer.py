from pathlib import Path
from uuid import uuid4

import pytest

from gorak.journal import (
    JournalEvent,
    acknowledgment_store,
    consume_journal,
    poll_journal,
)
from gorak.journal_observer import checkpoint_observer, stage_observer
from gorak.project import ProjectError
from tests.test_journal_server import SETTINGS, Server


def test_failed_staged_progress_cannot_hide_event_on_retry(tmp_path: Path) -> None:
    server = Server()
    identity = server.db.execute(
        'select installation_id from "$ingres".gorak_tracking_install'
    ).fetchone()[0]
    published = tmp_path / "published.sqlite3"
    stage_observer(published, identity)
    original = published.read_bytes()
    server.add(1)
    failed = tmp_path / "failed.sqlite3"
    stage_observer(failed, identity, published)
    with acknowledgment_store(failed) as store:
        batch = poll_journal(SETTINGS, store, engine_factory=server.factory)
    checkpoint_observer(failed, batch.events)
    assert published.read_bytes() == original
    assert server.db.execute(
        'select count(*) from "$ingres".gorak_journal_acks'
    ).fetchone() == (0,)
    retry = tmp_path / "retry.sqlite3"
    stage_observer(retry, identity, published)
    with acknowledgment_store(retry) as store:
        assert [
            e.event_id
            for e in poll_journal(SETTINGS, store, engine_factory=server.factory).events
        ] == [1]


def test_published_observation_progress_is_independent_of_general_consumer(
    tmp_path: Path,
) -> None:
    server = Server()
    identity = server.db.execute(
        'select installation_id from "$ingres".gorak_tracking_install'
    ).fetchone()[0]
    server.add(1)
    with acknowledgment_store(tmp_path / "general.sqlite3") as store:
        consume_journal(SETTINGS, store, lambda e: None, engine_factory=server.factory)
        assert not poll_journal(SETTINGS, store, engine_factory=server.factory).events
    first = tmp_path / "first.sqlite3"
    observer_id = stage_observer(first, identity)
    with acknowledgment_store(first) as store:
        batch = poll_journal(SETTINGS, store, engine_factory=server.factory)
        assert [e.event_id for e in batch.events] == [1]
    checkpoint_observer(first, batch.events)
    original = first.read_bytes()
    second = tmp_path / "second.sqlite3"
    assert stage_observer(second, identity, first) == observer_id
    with acknowledgment_store(second) as store:
        assert not poll_journal(SETTINGS, store, engine_factory=server.factory).events
    assert first.read_bytes() == original
    with acknowledgment_store(tmp_path / "another-general.sqlite3") as store:
        assert (
            len(poll_journal(SETTINGS, store, engine_factory=server.factory).events)
            == 1
        )


def test_checkpoint_failure_rolls_back_local_ack_and_outbox(tmp_path: Path) -> None:
    path = tmp_path / "observer.sqlite3"
    stage_observer(path, str(uuid4()))
    with acknowledgment_store(path) as store:
        store.execute(
            "create trigger fail before insert on ack_outbox "
            "begin select raise(abort, 'disk failure'); end"
        )
        store.commit()
    with pytest.raises(ProjectError, match="storage failed"):
        checkpoint_observer(path, (JournalEvent(1, "ii_entities", "u", {}, {}),))
    with acknowledgment_store(path) as store:
        assert store.execute("select * from acknowledged").fetchall() == []
        assert store.execute("select * from ack_outbox").fetchall() == []

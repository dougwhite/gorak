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


def test_old_checkpoint_is_rejected_after_newer_receipts_are_published(
    tmp_path: Path,
) -> None:
    server = Server()
    identity = server.db.execute(
        'select installation_id from "$ingres".gorak_tracking_install'
    ).fetchone()[0]
    old = tmp_path / "old.sqlite3"
    stage_observer(old, identity)
    server.add(1)
    checkpoint_observer(old, (JournalEvent(1, "ii_entities", "u", {}, {}),))
    newer = tmp_path / "newer.sqlite3"
    stage_observer(newer, identity, old)
    with acknowledgment_store(newer) as store:
        poll_journal(
            SETTINGS, store, engine_factory=server.factory, verify_receipts=True
        )
    server.add(2)
    checkpoint_observer(newer, (JournalEvent(2, "ii_entities", "u", {}, {}),))
    with acknowledgment_store(newer) as store:
        poll_journal(
            SETTINGS, store, engine_factory=server.factory, verify_receipts=True
        )
    restored = tmp_path / "restored.sqlite3"
    stage_observer(restored, identity, old)
    with acknowledgment_store(restored) as store:
        with pytest.raises(ProjectError, match="differ from local history"):
            poll_journal(
                SETTINGS, store, engine_factory=server.factory, verify_receipts=True
            )


def test_missing_published_receipts_fail_before_event_processing(
    tmp_path: Path,
) -> None:
    server = Server()
    identity = server.db.execute(
        'select installation_id from "$ingres".gorak_tracking_install'
    ).fetchone()[0]
    path = tmp_path / "observer.sqlite3"
    observer_id = stage_observer(path, identity)
    server.add(1)
    checkpoint_observer(path, (JournalEvent(1, "ii_entities", "u", {}, {}),))
    with acknowledgment_store(path) as store:
        poll_journal(
            SETTINGS, store, engine_factory=server.factory, verify_receipts=True
        )
    server.db.execute(
        'delete from "$ingres".gorak_journal_acks where consumer_id=?', (observer_id,)
    )
    server.db.commit()
    with acknowledgment_store(path) as store:
        with pytest.raises(ProjectError, match="receipts are missing"):
            poll_journal(
                SETTINGS, store, engine_factory=server.factory, verify_receipts=True
            )


def test_same_count_different_receipt_ids_are_rejected(tmp_path: Path) -> None:
    server = Server()
    identity = server.db.execute(
        'select installation_id from "$ingres".gorak_tracking_install'
    ).fetchone()[0]
    path = tmp_path / "observer.sqlite3"
    observer_id = stage_observer(path, identity)
    server.add(1)
    checkpoint_observer(path, (JournalEvent(1, "ii_entities", "u", {}, {}),))
    with acknowledgment_store(path) as store:
        poll_journal(
            SETTINGS, store, engine_factory=server.factory, verify_receipts=True
        )
    server.db.execute(
        'update "$ingres".gorak_journal_acks set event_id=2 where consumer_id=?',
        (observer_id,),
    )
    server.db.commit()
    with acknowledgment_store(path) as store:
        with pytest.raises(ProjectError, match="differ from local history"):
            poll_journal(
                SETTINGS, store, engine_factory=server.factory, verify_receipts=True
            )


def test_uncertain_commit_receipt_in_outbox_is_accepted(tmp_path: Path) -> None:
    server = Server()
    identity = server.db.execute(
        'select installation_id from "$ingres".gorak_tracking_install'
    ).fetchone()[0]
    path = tmp_path / "observer.sqlite3"
    observer_id = stage_observer(path, identity)
    server.add(1)
    checkpoint_observer(path, (JournalEvent(1, "ii_entities", "u", {}, {}),))
    server.db.execute(
        'insert into "$ingres".gorak_journal_acks values (?,1)', (observer_id,)
    )
    server.db.commit()
    with acknowledgment_store(path) as store:
        assert not poll_journal(
            SETTINGS, store, engine_factory=server.factory, verify_receipts=True
        ).events
        assert store.execute("select event_id from published").fetchall() == [(1,)]

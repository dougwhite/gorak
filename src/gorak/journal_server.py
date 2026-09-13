"""Server-side acknowledgment selection, with durable local publication receipts."""

import sqlite3
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from .project import ProjectError

ACK_SQL = """
insert into "$ingres".gorak_journal_acks (consumer_id, event_id)
select :consumer, e.event_id from "$ingres".gorak_change_events e
where e.event_id = :event
and not exists (
    select 1 from "$ingres".gorak_journal_acks a
    where a.consumer_id = :consumer and a.event_id = e.event_id
)
"""
EXISTS_SQL = """
select event_id from "$ingres".gorak_journal_acks
where consumer_id = :consumer and event_id = :event
"""


def consumer_identity(store: sqlite3.Connection) -> str:
    store.execute("create table if not exists consumer (id text primary key)")
    store.execute("create table if not exists published (event_id integer primary key)")
    if not store.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'ack_outbox'"
    ).fetchone():
        store.execute("create table ack_outbox (event_id integer primary key)")
        store.execute(
            "insert into ack_outbox select event_id from acknowledged "
            "where event_id not in (select event_id from published)"
        )
        store.commit()
    rows = store.execute("select id from consumer").fetchall()
    if not rows:
        identity = str(uuid4())
        store.execute("insert into consumer values (?)", (identity,))
        store.commit()
        return identity
    if len(rows) != 1:
        raise ProjectError("Invalid local journal consumer identity")
    return str(rows[0][0])


def publish_acknowledgments(
    connection: Any, store: sqlite3.Connection, consumer: str
) -> None:
    """Publish only durable local acks. Retry after uncertain commit is idempotent."""
    while True:
        pending = store.execute("select event_id from ack_outbox limit 256").fetchall()
        if not pending:
            return
        for (event_id,) in pending:
            params = {"consumer": consumer, "event": event_id}
            connection.execute(text(ACK_SQL), params)
            if connection.execute(text(EXISTS_SQL), params).fetchone() is None:
                raise ProjectError(
                    "Acknowledged journal history is missing; verified rebootstrap required"
                )
        connection.commit()
        # Crash before this local commit resends the exact same IDs on next poll.
        with store:
            store.executemany("insert or ignore into published values (?)", pending)
            store.executemany("delete from ack_outbox where event_id = ?", pending)

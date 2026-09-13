"""Stage private observation progress alongside immutable snapshot evidence."""

import sqlite3
from contextlib import closing
from pathlib import Path

from .journal import JournalEvent, acknowledgment_store, bind_store
from .journal_server import consumer_identity


def stage_observer(
    destination: Path, installation_id: str, previous: Path | None = None
) -> str:
    """Copy previous progress; never mutate a published snapshot database."""
    if previous is not None:
        with closing(
            sqlite3.connect(previous.as_uri() + "?mode=ro", uri=True)
        ) as source:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
    with acknowledgment_store(destination) as store:
        bind_store(store, installation_id)
        return consumer_identity(store)


def checkpoint_observer(path: Path, events: tuple[JournalEvent, ...]) -> None:
    """Record exact observed IDs locally; caller must publish durable XML evidence.

    Server publication happens only when a later operation copies and polls this
    published checkpoint. A failed/unpublished operation cannot publish these IDs.
    """
    with acknowledgment_store(path) as store:
        consumer_identity(store)
        with store:
            for event in events:
                store.execute(
                    "insert or ignore into acknowledged values (?)", (event.event_id,)
                )
                store.execute(
                    "insert or ignore into ack_outbox values (?)", (event.event_id,)
                )

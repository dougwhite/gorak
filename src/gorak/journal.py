"""Replayable journal consumer prototype with checkout-local acknowledgments.

This reads event metadata, not source payloads. It deliberately does not authorize
incremental status. Schema v2 selects pending events on the database server.
"""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .installation import FIELDS, SCHEMA_VERSION, TABLES
from .journal_server import consumer_identity, publish_acknowledgments
from .project import ProjectError

COLUMNS = ["event_id", "source_table", "action"] + [
    f"{side}_{name}" for side in ("old", "new") for name in FIELDS
]
EVENT_SQL = "select " + ", ".join(COLUMNS) + ' from "$ingres".gorak_change_events'
MARKER_SQL = (
    'select schema_version, installation_id, mode from "$ingres".gorak_tracking_install'
)


@dataclass(frozen=True)
class JournalEvent:
    event_id: int
    source_table: str
    action: str
    old: dict[str, int | str | None]
    new: dict[str, int | str | None]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class JournalBatch:
    installation_id: str
    events: tuple[JournalEvent, ...]
    scanned_events: int


@contextmanager
def acknowledgment_store(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.execute("pragma synchronous = FULL")
        connection.execute(
            "create table if not exists installation (id text primary key)"
        )
        connection.execute(
            "create table if not exists acknowledged (event_id integer primary key)"
        )
        connection.commit()
        yield connection
    except sqlite3.Error as ex:
        raise ProjectError(
            "Journal acknowledgment storage failed; preserve local state and retry after resolving the storage error"
        ) from ex
    finally:
        connection.close()


def bind_store(store: sqlite3.Connection, installation_id: str) -> None:
    rows = store.execute("select id from installation").fetchall()
    if not rows:
        store.execute("insert into installation values (?)", (installation_id,))
        store.commit()
    elif rows != [(installation_id,)]:
        raise ProjectError(
            "Journal installation identity changed; run gorak journal --rebootstrap for a verified full observation"
        )


def poll_journal(
    settings: OdbcSettings,
    store: sqlite3.Connection,
    limit: int = 100,
    engine_factory: EngineFactory = create_odbc_engine,
) -> JournalBatch:
    """Return at most limit unacknowledged events from a fresh committed read."""
    if not 1 <= limit <= 10000:
        raise ProjectError("Journal limit must be between 1 and 10000")
    engine = engine_factory(settings)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "set lockmode session where level = mvcc, readlock = shared, timeout = 5"
                )
            )
            rows = list(connection.execute(text(MARKER_SQL)))
            if (
                len(rows) != 1
                or rows[0][0] not in (1, SCHEMA_VERSION)
                or str(rows[0][2]).strip() != "capture_only"
            ):
                raise ProjectError("Unsupported journal installation record")
            try:
                identity = UUID(str(rows[0][1]).strip())
                if not identity.int:
                    raise ValueError
            except ValueError as ex:
                raise ProjectError("Invalid journal installation UUID") from ex
            installation_id = str(identity)
            bind_store(store, installation_id)
            query = EVENT_SQL
            params: dict[str, str] = {}
            if rows[0][0] == 2:
                consumer = consumer_identity(store)
                publish_acknowledgments(connection, store, consumer)
                # No high-water cursor: a lower ID can commit after a higher ID.
                query = (
                    f"select first {limit} "
                    + ", ".join("e." + name for name in COLUMNS)
                    + ' from "$ingres".gorak_change_events e where not exists ('
                    + 'select 1 from "$ingres".gorak_journal_acks a '
                    + "where a.consumer_id = :consumer and a.event_id = e.event_id)"
                )
                params = {"consumer": consumer}
            events: list[JournalEvent] = []
            scanned = 0
            result = (
                connection.execute(text(query), params)
                if params
                else connection.execute(text(query))
            )
            try:
                while len(events) < limit:
                    # Stream metadata; do not materialize a potentially huge journal.
                    chunk = result.fetchmany(min(256, limit - len(events)))
                    if not chunk:
                        break
                    for row in chunk:
                        scanned += 1
                        event_id = int(row[0])
                        if store.execute(
                            "select 1 from acknowledged where event_id = ?", (event_id,)
                        ).fetchone():
                            continue
                        table, action = str(row[1]).strip(), str(row[2]).strip()
                        if (
                            event_id <= 0
                            or table not in TABLES
                            or action not in {"i", "u", "d"}
                        ):
                            raise ProjectError("Invalid source journal event")
                        values = list(row[3:])
                        sides: list[dict[str, int | str | None]] = []
                        for offset in (0, len(FIELDS)):
                            side: dict[str, int | str | None] = {}
                            for index, (name, kind) in enumerate(FIELDS.items()):
                                value = values[offset + index]
                                side[name] = (
                                    None
                                    if value is None
                                    else str(value).strip()
                                    if kind.startswith("varchar")
                                    else int(value)
                                )
                            sides.append(side)
                        events.append(
                            JournalEvent(event_id, table, action, sides[0], sides[1])
                        )
            finally:
                result.close()
            return JournalBatch(installation_id, tuple(events), scanned)
    except (ValueError, TypeError, IndexError) as ex:
        raise ProjectError(
            "Invalid source journal data; no events acknowledged"
        ) from ex
    finally:
        engine.dispose()


def consume_journal(
    settings: OdbcSettings,
    store: sqlite3.Connection,
    process: Callable[[JournalEvent], None],
    limit: int = 100,
    engine_factory: EngineFactory = create_odbc_engine,
) -> JournalBatch:
    """Process then durably acknowledge each event; callbacks must be replay-safe.

    The caller holds the checkout lock and must durably persist verified work before
    returning from process. Failure between work and acknowledgment replays that work.
    """
    batch = poll_journal(settings, store, limit, engine_factory)
    for event in batch.events:
        process(event)
        with store:
            store.execute(
                "insert or ignore into acknowledged values (?)", (event.event_id,)
            )
            if store.execute(
                "select 1 from sqlite_master where type = 'table' and name = 'ack_outbox'"
            ).fetchone():
                store.execute(
                    "insert or ignore into ack_outbox values (?)", (event.event_id,)
                )
    return batch

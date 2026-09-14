"""Bounded journal candidates certified by managed revision increments.

An event ID is only a query accelerator, never a commit watermark. The caller
must bracket this read and its semantic observation with equal healthy revision
samples, and bind the saved maximum and vector to the same verified snapshot.
"""

from dataclasses import dataclass

from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .installation import FIELDS, TABLES
from .journal import COLUMNS, JournalEvent
from .revision_observation import BoundRevisionSample

MAX_EVENTS = 4096
MAX_OBJECTS = 128


@dataclass(frozen=True)
class AffectedSource:
    events: tuple[JournalEvent, ...] = ()
    object_ids: tuple[int, ...] = ()
    maximum: int = 0
    fallback: str | None = None


def revision_delta(
    previous: BoundRevisionSample, current: BoundRevisionSample
) -> int | None:
    """Count committed event inserts; missing/decreasing lanes cannot certify a range."""
    if (
        previous.revision_id != current.revision_id
        or previous.parent_installation_id != current.parent_installation_id
        or previous.sample.lanes is None
        or current.sample.lanes is None
    ):
        return None
    old = {(s, p): n for s, p, n in previous.sample.lanes}
    new = {(s, p): n for s, p, n in current.sample.lanes}
    if any(key not in new or new[key] < value for key, value in old.items()):
        return None
    return sum(new.values()) - sum(old.values())


def select_affected(
    settings: OdbcSettings,
    previous: BoundRevisionSample,
    current: BoundRevisionSample,
    maximum: int,
    engine_factory: EngineFactory = create_odbc_engine,
) -> AffectedSource:
    """Read a bounded ID range and demand exact agreement with captured insert count.

    A late lower-ID commit, pruned new event, reset lane, oversized change or shared
    storage edit requests full XML. No receipts, source writes, or acknowledgments.
    Object IDs include BOTH sides; ownership/type resolution is the caller's job.
    """
    count = revision_delta(previous, current)
    if type(maximum) is not int or maximum < 0 or count is None:
        return AffectedSource(fallback="uncertified_revision_range")
    if count > MAX_EVENTS:
        return AffectedSource(fallback="event_budget_exceeded")
    if count == 0:
        return AffectedSource(maximum=maximum)
    engine = engine_factory(settings)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "set lockmode session where level=mvcc, readlock=shared, timeout=5"
                )
            )
            result = connection.execute(
                text(
                    f"select first {count + 1} "
                    + ",".join(COLUMNS)
                    + ' from "$ingres".gorak_change_events where event_id > :maximum'
                ),
                {"maximum": maximum},
            )
            try:
                rows = result.fetchmany(count + 1)
            finally:
                result.close()
        if len(rows) != count:
            return AffectedSource(fallback="event_count_disagrees_with_revisions")
        events = []
        seen: set[int] = set()
        objects: set[int] = set()
        for row in rows:
            if len(row) != len(COLUMNS):
                raise ValueError
            identity, table, action = row[:3]
            if (
                type(identity) is not int
                or identity <= maximum
                or identity in seen
                or not isinstance(table, str)
                or not isinstance(action, str)
            ):
                raise ValueError
            table, action = table.strip(), action.strip()
            if table not in TABLES or action not in {"i", "u", "d"}:
                raise ValueError
            seen.add(identity)
            if table.startswith("ii_stored_"):
                return AffectedSource(fallback="shared_storage_ownership_unsupported")
            sides: list[dict[str, int | str | None]] = []
            for offset in (3, 3 + len(FIELDS)):
                side: dict[str, int | str | None] = {}
                for index, (name, kind) in enumerate(FIELDS.items()):
                    value = row[offset + index]
                    if value is not None:
                        if kind.startswith("varchar"):
                            if not isinstance(value, str):
                                raise ValueError
                            value = value.strip()
                        elif type(value) is not int:
                            raise ValueError
                    side[name] = value
                identity = side["object_id"]
                if identity is not None:
                    if type(identity) is not int or identity <= 0:
                        raise ValueError
                    objects.add(identity)
                sides.append(side)
            if not any(side["object_id"] is not None for side in sides):
                return AffectedSource(fallback="missing_object_identity")
            events.append(JournalEvent(row[0], table, action, *sides))
        if len(objects) > MAX_OBJECTS:
            return AffectedSource(fallback="object_budget_exceeded")
        return AffectedSource(
            tuple(sorted(events, key=lambda event: event.event_id)),
            tuple(sorted(objects)),
            max(seen),
        )
    except (ValueError, TypeError, IndexError):
        return AffectedSource(fallback="invalid_candidate_rows")
    finally:
        engine.dispose()

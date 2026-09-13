"""Bound diagnostic export windows using committed append-only journal metadata.

This is not a cursor or restore detector. Counting retained events can be expensive.
"""

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .installation import SCHEMA_VERSION
from .project import ProjectError

OBSERVATION_SQL = """
select m.schema_version, m.installation_id, m.mode,
       count(e.event_id), max(e.event_id)
from "$ingres".gorak_tracking_install m
left join "$ingres".gorak_change_events e on 1 = 1
group by m.schema_version, m.installation_id, m.mode
"""


@dataclass(frozen=True)
class JournalObservation:
    schema_version: int
    installation_id: str
    event_count: int
    max_event_id: int | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def observe_journal(
    settings: OdbcSettings,
    engine_factory: EngineFactory = create_odbc_engine,
) -> JournalObservation:
    """Use one committed statement on a fresh connection, independent of polling."""
    engine = engine_factory(settings)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "set lockmode session where level = mvcc, readlock = shared, timeout = 5"
                )
            )
            rows = list(connection.execute(text(OBSERVATION_SQL)))
            if len(rows) != 1:
                raise ValueError
            version, identity, mode, count, maximum = rows[0]
            identity = UUID(str(identity).strip())
            count = int(count)
            maximum = None if maximum is None else int(maximum)
            if (
                version not in (1, SCHEMA_VERSION)
                or not identity.int
                or str(mode).strip() != "capture_only"
                or count < 0
                or (count == 0) != (maximum is None)
                or (maximum is not None and maximum < count)
            ):
                raise ValueError
            return JournalObservation(int(version), str(identity), count, maximum)
    except (ValueError, TypeError) as ex:
        raise ProjectError(
            "Invalid journal observation; snapshot not published"
        ) from ex
    finally:
        engine.dispose()

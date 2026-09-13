"""Bounded entity metadata for full-reference diagnostic snapshots."""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .journal_mapping import Entity
from .project import ProjectError

MAX_SNAPSHOT_ENTITIES = 100000


def parse_entities(rows: Any) -> tuple[Entity, ...]:
    if not isinstance(rows, list) or len(rows) > MAX_SNAPSHOT_ENTITIES:
        raise ValueError("Invalid ancestry snapshot")
    entities = []
    identities = set()
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 5
            or any(type(value) is not int for value in row[:3])
            or row[0] <= 0
            or row[1] < 0
            or row[2] < 0
            or not all(isinstance(value, str) for value in row[3:])
            or row[0] in identities
        ):
            raise ValueError("Invalid ancestry entity")
        identities.add(row[0])
        entities.append(Entity(*row))
    return tuple(entities)


def read_ancestry(
    settings: OdbcSettings, engine_factory: EngineFactory = create_odbc_engine
) -> tuple[Entity, ...] | None:
    """Return no history when the metadata budget is exceeded; never read source."""
    engine = engine_factory(settings)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "set lockmode session where level = mvcc, readlock = shared, timeout = 5"
                )
            )
            result = connection.execute(
                text(
                    f"select first {MAX_SNAPSHOT_ENTITIES + 1} "
                    "entity_id, folder_id, base_entity_id, entity_name, entity_type "
                    'from "$ingres".ii_entities'
                )
            )
            try:
                rows = list(result)
            finally:
                result.close()
            if len(rows) > MAX_SNAPSHOT_ENTITIES:
                return None
            return parse_entities(
                [
                    [
                        int(r[0]),
                        int(r[1] or 0),
                        int(r[2] or 0),
                        str(r[3] or "").strip(),
                        str(r[4] or "").strip().casefold(),
                    ]
                    for r in rows
                ]
            )
    except (ValueError, TypeError, IndexError) as ex:
        raise ProjectError("Invalid entity ancestry; snapshot not published") from ex
    finally:
        engine.dispose()


def write_ancestry(path: Path, entities: tuple[Entity, ...] | None) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(
            None
            if entities is None
            else [[e.identity, e.parent, e.base, e.name, e.kind] for e in entities],
            stream,
        )


def load_ancestry(path: Path) -> tuple[Entity, ...] | None:
    rows = json.loads(path.read_text())
    return None if rows is None else parse_entities(rows)

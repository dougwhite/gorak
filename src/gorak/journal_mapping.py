"""Conservative application candidates from current metadata and event tombstones."""

from dataclasses import asdict, dataclass

from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .installation import TABLES
from .journal import MARKER_SQL, JournalBatch, JournalEvent
from .project import ProjectError

SHARED_STORAGE = {"ii_stored_strings", "ii_stored_nstrings", "ii_stored_bitmaps"}
MAX_DEPTH = 16
MAX_IDENTITIES = 10000


@dataclass(frozen=True)
class Entity:
    identity: int
    parent: int
    base: int
    name: str
    kind: str


@dataclass(frozen=True)
class EventApplications:
    event_id: int
    applications: tuple[str, ...]
    full_comparison: bool
    reason: str


@dataclass(frozen=True)
class ApplicationCandidates:
    applications: tuple[str, ...]
    full_comparison: bool
    events: tuple[EventApplications, ...]
    metadata_queries: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def positive_id(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else 0
    )


def entity_from_side(side: dict[str, int | str | None]) -> Entity | None:
    identity = positive_id(side.get("object_id"))
    if not identity:
        return None
    return Entity(
        identity,
        positive_id(side.get("parent_id")),
        positive_id(side.get("base_id")),
        str(side.get("object_name") or "").strip(),
        str(side.get("object_type") or "").strip().casefold(),
    )


def sides(event: JournalEvent) -> tuple[dict[str, int | str | None], ...]:
    if event.action == "i":
        return (event.new,)
    if event.action == "d":
        return (event.old,)
    return (event.old, event.new)


def resolve(
    identity: int,
    entities: dict[int, set[Entity]],
    visited: frozenset[int] = frozenset(),
) -> tuple[set[str], bool]:
    if identity in visited or len(visited) >= MAX_DEPTH or identity not in entities:
        return set(), False
    applications: set[str] = set()
    complete = True
    for entity in entities[identity]:
        if entity.kind == "appsource":
            if not entity.name or any(c in entity.name for c in "/\\\x00\r\n"):
                complete = False
            else:
                applications.add(entity.name.casefold())
            continue
        # Version rows can have no folder; their base row carries the parent.
        parents = {value for value in (entity.parent, entity.base) if value > 0}
        if not parents:
            complete = False
        for parent in parents:
            names, known = resolve(parent, entities, visited | {identity})
            applications.update(names)
            complete = complete and known
    return applications, complete and bool(applications)


def map_applications(
    settings: OdbcSettings,
    batch: JournalBatch,
    engine_factory: EngineFactory = create_odbc_engine,
) -> ApplicationCandidates:
    """Do not acknowledge events or authorize cached source reuse.

    Missing history, shared storage and bounded traversal exhaustion force full
    comparison. Both historical and current identity edges are retained.
    """
    if not batch.events:
        return ApplicationCandidates((), False, (), 0)
    entities: dict[int, set[Entity]] = {}
    requested: set[int] = set()
    historical_old_ids = {
        positive_id(event.old.get("object_id"))
        for event in batch.events
        if event.source_table == "ii_entities" and event.action in {"u", "d"}
    }
    for event in batch.events:
        if event.source_table in SHARED_STORAGE:
            continue
        for side in sides(event):
            identity = positive_id(side.get("object_id"))
            if identity:
                requested.add(identity)
            if event.source_table == "ii_entities":
                historical = entity_from_side(side)
                if historical is not None:
                    entities.setdefault(historical.identity, set()).add(historical)
                    requested.update(
                        i for i in (historical.parent, historical.base) if i
                    )

    engine = engine_factory(settings)
    queries = 0
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "set lockmode session where level = mvcc, readlock = shared, timeout = 5"
                )
            )

            def verify_identity() -> None:
                marker = list(connection.execute(text(MARKER_SQL)))
                if (
                    len(marker) != 1
                    or marker[0][0] not in (1, 2)
                    or str(marker[0][1]).strip().lower()
                    != batch.installation_id.lower()
                    or str(marker[0][2]).strip() != "capture_only"
                ):
                    raise ProjectError(
                        "Journal installation changed during application mapping"
                    )

            verify_identity()
            fetched: set[int] = set()
            for _ in range(MAX_DEPTH):
                pending = sorted(requested - fetched)
                if not pending or len(fetched) + len(pending) > MAX_IDENTITIES:
                    break
                for start in range(0, len(pending), 128):
                    ids = pending[start : start + 128]
                    params = {f"id{i}": value for i, value in enumerate(ids)}
                    placeholders = ", ".join(":" + key for key in params)
                    query = (
                        "select entity_id, folder_id, base_entity_id, entity_name, entity_type "
                        'from "$ingres".ii_entities where entity_id in ('
                        + placeholders
                        + ")"
                    )
                    queries += 1
                    for row in connection.execute(text(query), params):
                        entity = Entity(
                            int(row[0]),
                            int(row[1] or 0),
                            int(row[2] or 0),
                            str(row[3] or "").strip(),
                            str(row[4] or "").strip().casefold(),
                        )
                        entities.setdefault(entity.identity, set()).add(entity)
                        if entity.kind != "appsource":
                            requested.update(
                                i for i in (entity.parent, entity.base) if i > 0
                            )
                    fetched.update(ids)
            verify_identity()
    finally:
        engine.dispose()

    results: list[EventApplications] = []
    all_applications: set[str] = set()
    for event in batch.events:
        applications: set[str] = set()
        complete = True
        reason = ""
        if event.source_table in SHARED_STORAGE:
            complete, reason = False, "Shared string/image ownership is not yet mapped"
        elif event.source_table not in TABLES or event.action not in {"i", "u", "d"}:
            complete, reason = False, "Unsupported event"
        else:
            for side in sides(event):
                identity = positive_id(side.get("object_id"))
                names, known = resolve(identity, entities)
                applications.update(names)
                complete = complete and known
            if (
                event.action == "d"
                and event.source_table != "ii_entities"
                and positive_id(event.old.get("object_id")) not in historical_old_ids
            ):
                complete = False
            if not complete:
                reason = "Missing historical ownership or unresolved/cyclic entity ancestry; full comparison required"
        all_applications.update(applications)
        results.append(
            EventApplications(
                event.event_id, tuple(sorted(applications)), not complete, reason
            )
        )
    return ApplicationCandidates(
        tuple(sorted(all_applications)),
        any(r.full_comparison for r in results),
        tuple(results),
        queries,
    )

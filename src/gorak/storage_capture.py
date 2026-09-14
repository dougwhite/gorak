"""Consistent, bounded ODBC capture of a current application/include closure."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .encoded_graph import UnsupportedSource
from .storage_archive import MAX_ARCHIVE, MAX_ROWS, TABLE_COLUMNS, Archive, Row

MAX_APPLICATIONS = 128


@dataclass
class _Reader:
    connection: Any
    characters: int = 0

    def rows(
        self, query: str, parameters: dict[str, object] | None = None
    ) -> list[Row]:
        result = self.connection.execute(text(query), parameters or {})
        rows: list[Row] = []
        try:
            keys = list(result.keys())
            while batch := result.fetchmany(1000):
                for row in batch:
                    values = dict(zip(keys, row, strict=True))
                    self.characters += sum(
                        len(v) if isinstance(v, str) else 4 for v in values.values()
                    )
                    if self.characters > MAX_ARCHIVE or len(rows) >= MAX_ROWS:
                        raise UnsupportedSource("source_capture_budget_exceeded")
                    rows.append(values)
        finally:
            result.close()
        return rows


def _ids(values: set[int]) -> str:
    # Only database integer identities reach this SQL identifier list.
    if (
        not values
        or len(values) > MAX_ROWS
        or any(type(v) is not int or not 1 <= v < 2**31 for v in values)
    ):
        raise UnsupportedSource("invalid_capture_identity_set")
    return ",".join(map(str, sorted(values)))


def capture(
    settings: OdbcSettings,
    applications: list[str],
    *,
    engine_factory: EngineFactory = create_odbc_engine,
) -> tuple[Archive, int]:
    """Full snapshot with shared table locks; never used by incremental status.

    Missing dependency handles are made symbolic only after proving they no longer
    exist. Live out-of-scope handles remain an explicit failure.
    """
    if (
        not applications
        or len(applications) > MAX_APPLICATIONS
        or any(not name or not name.isascii() for name in applications)
    ):
        raise UnsupportedSource("invalid_capture_application_scope")
    engine = engine_factory(settings)
    stale = 0
    try:
        with engine.connect() as connection:
            connection.execute(text("set session isolation level serializable"))
            connection.execute(
                text("set lockmode session where level=table,readlock=shared,timeout=5")
            )
            reader = _Reader(connection)
            pending = {name.casefold() for name in applications}
            apps: dict[str, Row] = {}
            while pending:
                name = min(pending)
                pending.remove(name)
                if name in apps:
                    continue
                if len(apps) >= MAX_APPLICATIONS:
                    raise UnsupportedSource("source_include_budget_exceeded")
                rows = reader.rows(
                    "select * from \"$ingres\".ii_entities where lower(entity_name)=:name and entity_type='appsource' and version_number=-1",
                    {"name": name},
                )
                if len(rows) != 1:
                    raise UnsupportedSource("missing_or_ambiguous_source_application")
                app = rows[0]
                apps[name] = app
                includes = reader.rows(
                    'select * from "$ingres".ii_incl_apps where app_id=:identity',
                    {"identity": app["entity_id"]},
                )
                for row in includes:
                    filename, included = row["incl_filename"], row["incl_name"]
                    if (
                        not isinstance(filename, str)
                        or not isinstance(included, str)
                        or not included
                    ):
                        raise UnsupportedSource("invalid_source_include")
                    if not filename.strip() and included.casefold() not in apps:
                        pending.add(included.casefold())
            scope: set[int] = set()
            for app in apps.values():
                for key in ("entity_id", "base_entity_id"):
                    value = app[key]
                    if type(value) is not int:
                        raise UnsupportedSource("invalid_application_identity")
                    scope.add(value)
            values = _ids(scope)
            entities = reader.rows(
                'select * from "$ingres".ii_entities where (entity_id in ('
                + values
                + ") or base_entity_id in ("
                + values
                + ") or folder_id in ("
                + values
                + ")) and version_number in (0,-1)"
            )
            identities = {row["entity_id"] for row in entities}
            if any(type(value) is not int for value in identities):
                raise UnsupportedSource("invalid_capture_entity_identity")
            ids = {int(str(value)) for value in identities}
            values = _ids(ids)
            tables = {"ii_entities": entities}
            for table in TABLE_COLUMNS:
                if table == "ii_entities":
                    continue
                key = {
                    "ii_incl_apps": "app_id",
                    "ii_longremarks": "object_id",
                    "ii_dependencies": "src_entity_id",
                    "ii_app_cntns_comp": "app_id",
                }.get(table, "entity_id")
                tables[table] = reader.rows(
                    'select * from "$ingres".'
                    + table
                    + " where "
                    + key
                    + " in ("
                    + values
                    + ")"
                )
            unresolved: set[int] = set()
            for row in tables["ii_dependencies"]:
                value = row["dest_entity_id"]
                if type(value) is not int:
                    raise UnsupportedSource("invalid_dependency_identity")
                if value and value not in ids:
                    unresolved.add(value)
            if unresolved:
                live = reader.rows(
                    'select entity_id from "$ingres".ii_entities where entity_id in ('
                    + _ids(unresolved)
                    + ")"
                )
                if live:
                    raise UnsupportedSource(
                        "live_external_dependency_requires_source_scope"
                    )
                for row in tables["ii_dependencies"]:
                    if row["dest_entity_id"] in unresolved:
                        if (
                            row["dependency_origin"]
                            not in {"4GL_COMPILER", "CLASS_EDITOR"}
                            or row["rel_class_type"] not in {"REFERENCES", "INHERITS"}
                            or not row["dest_app_name"]
                            or not row["dest_comp_name"]
                        ):
                            raise UnsupportedSource("unsupported_stale_dependency")
                        row["dest_entity_id"] = 0
                        stale += 1
        archive = Archive(tables)
        ordered = sorted(ids)
        return archive.remap(
            {value: index + 1 for index, value in enumerate(ordered)}
        ), stale
    finally:
        engine.dispose()

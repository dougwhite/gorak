"""Direct ODBC access to OpenROAD source database metadata."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

import pyodbc
from sqlalchemy import create_engine, text

from .domain import Application, ComponentInfo, IncludedApplication


@dataclass(frozen=True)
class OdbcSettings:
    """Connection settings for the Actian Ingres ODBC driver."""

    driver: str
    host: str
    listen_address: str
    database: str
    user: str
    password: str


@dataclass(frozen=True)
class ComponentSyncMetadata:
    """OpenROAD component change metadata used by `gorak sync`."""

    application_name: str
    component_name: str
    entity_type: str
    base_entity_id: int
    version_entity_id: int
    version_number: int
    alter_date: str
    alter_count: int
    last_altered_by: str
    current_make: int


EngineFactory = Callable[[OdbcSettings], Any]

APP_LIST_SQL = """
select e.entity_name as application_name, a.proc_start as start_component, e.short_remark
from ii_applications a
left join ii_entities e on a.entity_id = e.entity_id
"""

COMPONENT_LIST_SQL = """
select ea.entity_name as application_name, e.entity_name as component_name, e.entity_type, e.short_remark
from ii_entities e
left join ii_entities ea on e.folder_id = ea.entity_id
left join ii_applications a on ea.base_entity_id = a.entity_id
where e.base_entity_id = 0
and e.folder_id != 0
and lower(ea.entity_name) = lower(:app_name)
"""

INCLUDE_LIST_SQL = """
select e.entity_name as application_name, i.incl_name, i.incl_filename, i.incl_sequence
from ii_incl_apps i
left join ii_entities e on i.app_id = e.entity_id
where i.incl_name != 'core'
and lower(e.entity_name) = lower(:app_name)
order by i.incl_sequence
"""

COMPONENT_SYNC_METADATA_SQL = """
select case when app_current.entity_name is null
            then app_folder.entity_name
            else app_current.entity_name
       end as application_name,
       base.entity_name as component_name,
       base.entity_type,
       base.entity_id as base_entity_id,
       ver.entity_id as version_entity_id,
       ver.version_number,
       c.alter_date,
       c.alter_count,
       c.last_altered_by,
       c.current_make
from ii_entities base
left join ii_entities app_folder on base.folder_id = app_folder.entity_id
left join ii_entities app_current on app_current.base_entity_id = app_folder.entity_id
left join ii_applications a on a.entity_id = app_current.entity_id
left join ii_entities ver on ver.base_entity_id = base.entity_id
                         and ver.version_number = -1
left join ii_components c on c.entity_id = ver.entity_id
where base.base_entity_id = 0
and base.folder_id != 0
and lower(case when app_current.entity_name is null
               then app_folder.entity_name
               else app_current.entity_name
          end) = lower(:app_name)
order by base.entity_name
"""

ALL_COMPONENT_SYNC_METADATA_SQL = """
select case when app_current.entity_name is null
            then app_folder.entity_name
            else app_current.entity_name
       end as application_name,
       base.entity_name as component_name,
       base.entity_type,
       base.entity_id as base_entity_id,
       ver.entity_id as version_entity_id,
       ver.version_number,
       c.alter_date,
       c.alter_count,
       c.last_altered_by,
       c.current_make
from ii_entities base
left join ii_entities app_folder on base.folder_id = app_folder.entity_id
left join ii_entities app_current on app_current.base_entity_id = app_folder.entity_id
left join ii_applications a on a.entity_id = app_current.entity_id
left join ii_entities ver on ver.base_entity_id = base.entity_id
                         and ver.version_number = -1
left join ii_components c on c.entity_id = ver.entity_id
where base.base_entity_id = 0
and base.folder_id != 0
order by application_name, base.entity_name
"""


def build_odbc_connection_string(settings: OdbcSettings) -> str:
    """Build the Actian ODBC connection string used by pyodbc."""

    return (
        f"Driver={{{settings.driver}}};"
        f"HostName={settings.host};"
        f"ListenAddress={settings.listen_address};"
        f"Database={settings.database};"
        f"UID={settings.user};"
        f"PWD={settings.password}"
    )


def create_odbc_engine(settings: OdbcSettings) -> Any:
    """Create a SQLAlchemy engine through pyodbc's Actian connection string."""

    connection_string = build_odbc_connection_string(settings)
    return create_engine(
        "ingres://",
        creator=lambda: pyodbc.connect(connection_string),
    )


def get_app_list(
    settings: OdbcSettings,
    engine_factory: EngineFactory = create_odbc_engine,
) -> list[Application]:
    """Read OpenROAD applications through direct ODBC SQL."""

    engine = engine_factory(settings)
    with engine.connect() as connection:
        rows = connection.execute(text(APP_LIST_SQL))
        return applications_from_rows(row_mappings(rows))


def get_component_list(
    settings: OdbcSettings,
    app: str,
    engine_factory: EngineFactory = create_odbc_engine,
) -> list[ComponentInfo]:
    """Read OpenROAD components for one application through direct ODBC SQL."""

    engine = engine_factory(settings)
    with engine.connect() as connection:
        rows = connection.execute(text(COMPONENT_LIST_SQL), {"app_name": app})
        return components_from_rows(row_mappings(rows))


def get_include_list(
    settings: OdbcSettings,
    app: str,
    engine_factory: EngineFactory = create_odbc_engine,
) -> list[IncludedApplication]:
    """Read ordered included applications for one application through ODBC SQL."""

    engine = engine_factory(settings)
    with engine.connect() as connection:
        rows = connection.execute(text(INCLUDE_LIST_SQL), {"app_name": app})
        return includes_from_rows(row_mappings(rows))


def get_component_sync_metadata(
    settings: OdbcSettings,
    app: str,
    engine_factory: EngineFactory = create_odbc_engine,
) -> list[ComponentSyncMetadata]:
    """Read component change markers for one application through ODBC SQL."""

    engine = engine_factory(settings)
    with engine.connect() as connection:
        rows = connection.execute(text(COMPONENT_SYNC_METADATA_SQL), {"app_name": app})
        return component_sync_metadata_from_rows(row_mappings(rows))


def get_all_component_sync_metadata(
    settings: OdbcSettings,
    engine_factory: EngineFactory = create_odbc_engine,
) -> list[ComponentSyncMetadata]:
    """Read component change markers for all applications through ODBC SQL."""

    engine = engine_factory(settings)
    with engine.connect() as connection:
        rows = connection.execute(text(ALL_COMPONENT_SYNC_METADATA_SQL))
        return component_sync_metadata_from_rows(row_mappings(rows))


def applications_from_rows(rows: Iterable[Mapping[str, object]]) -> list[Application]:
    return [
        Application(
            name=clean_text(row["application_name"]),
            start_component=clean_text(row["start_component"]),
            description=clean_text(row["short_remark"]),
        )
        for row in rows
    ]


def components_from_rows(rows: Iterable[Mapping[str, object]]) -> list[ComponentInfo]:
    return [
        ComponentInfo(
            application_name=clean_text(row["application_name"]),
            name=clean_text(row["component_name"]),
            type=clean_text(row["entity_type"]),
            description=clean_text(row["short_remark"]),
        )
        for row in rows
    ]


def includes_from_rows(rows: Iterable[Mapping[str, object]]) -> list[IncludedApplication]:
    includes: list[IncludedApplication] = []
    for row in rows:
        name = clean_text(row["incl_name"])
        image = clean_text(row["incl_filename"])
        if not name or name.lower() == "core" or image.lower() == "core.plb":
            continue
        if image:
            includes.append({"name": name, "image": image})
        else:
            includes.append(name)

    return includes


def component_sync_metadata_from_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[ComponentSyncMetadata]:
    return [
        ComponentSyncMetadata(
            application_name=clean_text(row["application_name"]),
            component_name=clean_text(row["component_name"]),
            entity_type=clean_text(row["entity_type"]),
            base_entity_id=clean_int(row["base_entity_id"]),
            version_entity_id=clean_int(row["version_entity_id"]),
            version_number=clean_int(row["version_number"]),
            alter_date=clean_text(row["alter_date"]),
            alter_count=clean_int(row["alter_count"]),
            last_altered_by=clean_text(row["last_altered_by"]),
            current_make=clean_int(row["current_make"]),
        )
        for row in rows
    ]


def row_mappings(rows: Iterable[Any]) -> list[Mapping[str, object]]:
    return [
        row._mapping if hasattr(row, "_mapping") else row  # noqa: B009
        for row in rows
    ]


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def clean_int(value: object) -> int:
    if value is None:
        return 0
    return int(cast(str | bytes | bytearray | int, value))

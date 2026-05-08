"""Direct ODBC access to OpenROAD source database metadata."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

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


def row_mappings(rows: Iterable[Any]) -> list[Mapping[str, object]]:
    return [
        row._mapping if hasattr(row, "_mapping") else row  # noqa: B009
        for row in rows
    ]


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()

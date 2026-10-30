"""Compact sender change tokens; no source XML or receiver comparison."""

import re
from dataclasses import asdict

from sqlalchemy import text

from .connection import (
    OpenRoadConnection,
    connection_sql_backend,
    require_odbc_settings,
    require_remote_host,
)
from .database import create_odbc_engine
from .export import read_all_component_sync_metadata
from .project import ProjectError

APP_SQL = """select e.entity_name as application_name, a.entity_id,
a.alter_date, a.alter_count
from ii_applications a join ii_entities e on a.entity_id=e.entity_id
order by e.entity_name"""


def application_tokens(connection: OpenRoadConnection) -> dict[str, dict[str, object]]:
    from . import local, remote
    from .sql_output import table_rows

    backend = connection_sql_backend(connection)
    if backend == "odbc":
        engine = create_odbc_engine(require_odbc_settings(connection))
        try:
            with engine.connect() as db:
                rows = [
                    [str(v) if v is not None else "" for v in row]
                    for row in db.execute(text(APP_SQL))
                ]
        finally:
            engine.dispose()
    else:
        if backend == "local":
            output = local.run_subprocess(
                local.build_sql_command(connection.vnode, connection.database),
                APP_SQL + "\n\\p\\g\n\\q\n",
            )
        else:
            output = remote.run_subprocess(
                remote.build_remote_command(
                    remote=require_remote_host(connection),
                    script="get-app-sync-metadata.bat",
                    args=[connection.vnode, connection.database],
                )
            )
        if re.search(r"(?m)^\s*(?:\*\s*)?E_[A-Z0-9]+\b", output):
            raise ProjectError("Unable to read application change metadata")
        rows = table_rows(output, 4, "application_name")
    return {
        row[0]: {
            "name": row[0],
            "id": int(row[1]),
            "date": row[2],
            "count": int(row[3] or "0"),
        }
        for row in rows
    }


def inventory(connection: OpenRoadConnection) -> dict[str, dict[str, object]]:
    result = application_tokens(connection)
    metadata = read_all_component_sync_metadata(connection)
    for item in metadata:
        if item.base_entity_id <= 0 or item.version_entity_id <= 0:
            continue
        token = asdict(item)
        # Compilation is not a source edit.
        token.pop("current_make")
        token.pop("last_altered_by")
        result[f"{item.application_name}/{item.component_name}"] = token
    return result

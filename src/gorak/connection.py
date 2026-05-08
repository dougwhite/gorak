"""Resolve OpenROAD backend settings from CLI arguments and Gorak context."""

import argparse
from dataclasses import dataclass
from typing import Literal, cast

from .database import OdbcSettings
from .project import GorakContext, ProjectError
from .remote import RemoteHost

Backend = Literal["local", "remote"]
SqlBackend = Literal["local", "remote", "odbc"]
CONNECTION_HINTS = {
    "user": "--user/GORAK_REMOTE_USER",
    "host": "--host/GORAK_REMOTE_HOST",
    "gorak_root": "--gorak-root/GORAK_REMOTE_ROOT",
    "vnode": "--vnode/GORAK_VNODE",
    "database": "--database/GORAK_DATABASE",
    "db_driver": "--db-driver/GORAK_DB_DRIVER",
    "db_host": "--db-host/GORAK_DB_HOST",
    "db_listen_address": "--db-listen-address/GORAK_DB_LISTEN_ADDRESS",
    "db_user": "--db-user/GORAK_DB_USER",
    "db_password": "--db-password/GORAK_DB_PASSWORD",
}


@dataclass(frozen=True)
class OpenRoadConnection:
    backend: Backend
    vnode: str
    database: str
    remote_host: RemoteHost | None
    sql_backend: SqlBackend | None = None
    odbc_settings: OdbcSettings | None = None


def resolve_openroad_connection(
    args: argparse.Namespace, context: GorakContext
) -> OpenRoadConnection:
    env = context.env
    backend = resolve_backend(args, env)
    sql_backend = resolve_sql_backend(args, env, backend)

    openroad_values = {
        "vnode": env_value(args, "vnode", env, "GORAK_VNODE"),
        "database": env_value(args, "database", env, "GORAK_DATABASE"),
    }
    missing = [key for key, value in openroad_values.items() if value is None]
    needs_remote_host = backend == "remote" or sql_backend == "remote"
    if needs_remote_host:
        remote_values = remote_host_values(args, env)
        missing.extend(key for key, value in remote_values.items() if value is None)
    else:
        remote_values = {"user": None, "host": None, "gorak_root": None}

    if missing:
        raise ProjectError(
            "Missing OpenROAD connection settings: "
            + ", ".join(connection_hint(key) for key in missing)
        )

    odbc_settings = None
    if sql_backend == "odbc":
        odbc_settings = resolve_odbc_settings(args, env, openroad_values)

    return OpenRoadConnection(
        backend=backend,
        vnode=cast(str, openroad_values["vnode"]),
        database=cast(str, openroad_values["database"]),
        remote_host=(
            RemoteHost(
                user=cast(str, remote_values["user"]),
                host=cast(str, remote_values["host"]),
                gorak_root=cast(str, remote_values["gorak_root"]),
            )
            if needs_remote_host
            else None
        ),
        sql_backend=sql_backend,
        odbc_settings=odbc_settings,
    )


def resolve_backend(args: argparse.Namespace, env: dict[str, str]) -> Backend:
    configured = env_value(args, "backend", env, "GORAK_BACKEND")
    if configured in {"local", "remote"}:
        return cast(Backend, configured)
    if configured is not None:
        raise ProjectError(f"OpenROAD backend is not implemented: {configured}")
    if any(remote_host_values(args, env).values()):
        return "remote"
    return "local"


def resolve_sql_backend(
    args: argparse.Namespace,
    env: dict[str, str],
    openroad_backend: Backend,
) -> SqlBackend:
    configured = env_value(args, "sql_backend", env, "GORAK_SQL_BACKEND")
    if configured in {"local", "remote", "odbc"}:
        return cast(SqlBackend, configured)
    if configured is not None:
        raise ProjectError(f"SQL backend is not implemented: {configured}")
    return cast(SqlBackend, openroad_backend)


def resolve_odbc_settings(
    args: argparse.Namespace,
    env: dict[str, str],
    openroad_values: dict[str, str | None],
) -> OdbcSettings:
    values = {
        "db_driver": env_value(args, "db_driver", env, "GORAK_DB_DRIVER"),
        "db_host": env_value(args, "db_host", env, "GORAK_DB_HOST"),
        "db_listen_address": env_value(
            args,
            "db_listen_address",
            env,
            "GORAK_DB_LISTEN_ADDRESS",
        ),
        "database": env_value(args, "db_database", env, "GORAK_DB_DATABASE")
        or openroad_values["database"],
        "db_user": env_value(args, "db_user", env, "GORAK_DB_USER"),
        "db_password": env_value(args, "db_password", env, "GORAK_DB_PASSWORD"),
    }
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise ProjectError(
            "Missing ODBC connection settings: "
            + ", ".join(connection_hint(key) for key in missing)
        )

    return OdbcSettings(
        driver=cast(str, values["db_driver"]),
        host=cast(str, values["db_host"]),
        listen_address=cast(str, values["db_listen_address"]),
        database=cast(str, values["database"]),
        user=cast(str, values["db_user"]),
        password=cast(str, values["db_password"]),
    )


def resolve_remote_host(args: argparse.Namespace, context: GorakContext) -> RemoteHost:
    values = remote_host_values(args, context.env)
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise ProjectError(
            "Missing remote settings: "
            + ", ".join(connection_hint(key) for key in missing)
        )

    return RemoteHost(
        user=cast(str, values["user"]),
        host=cast(str, values["host"]),
        gorak_root=cast(str, values["gorak_root"]),
    )


def remote_host_values(
    args: argparse.Namespace,
    env: dict[str, str],
) -> dict[str, str | None]:
    return {
        "user": env_value(args, "user", env, "GORAK_REMOTE_USER"),
        "host": env_value(args, "host", env, "GORAK_REMOTE_HOST"),
        "gorak_root": env_value(args, "gorak_root", env, "GORAK_REMOTE_ROOT"),
    }


def env_value(
    args: argparse.Namespace,
    arg_name: str,
    env: dict[str, str],
    env_name: str,
) -> str | None:
    value = getattr(args, arg_name, None)
    if value:
        return cast(str, value)
    return env.get(env_name)


def connection_hint(key: str) -> str:
    return CONNECTION_HINTS[key]


def require_remote_host(connection: OpenRoadConnection) -> RemoteHost:
    if connection.remote_host is None:
        raise ProjectError("Remote host is required for remote OpenROAD backend")
    return connection.remote_host


def require_odbc_settings(connection: OpenRoadConnection) -> OdbcSettings:
    if connection.odbc_settings is None:
        raise ProjectError("ODBC settings are required for ODBC SQL backend")
    return connection.odbc_settings


def connection_sql_backend(connection: OpenRoadConnection) -> SqlBackend:
    return connection.sql_backend or cast(SqlBackend, connection.backend)


def connection_source(connection: OpenRoadConnection) -> str:
    if connection.backend == "local":
        return "local"
    return f"remote host {require_remote_host(connection).ssh_target}"

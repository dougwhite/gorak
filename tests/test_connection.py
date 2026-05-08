import argparse

import pytest

from gorak.connection import (
    OpenRoadConnection,
    connection_source,
    require_odbc_settings,
    require_remote_host,
    resolve_openroad_connection,
    resolve_remote_host,
)
from gorak.database import OdbcSettings
from gorak.project import GorakContext, ProjectError
from gorak.remote import RemoteHost


def args(**values: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "backend": None,
        "user": None,
        "host": None,
        "gorak_root": None,
        "vnode": None,
        "database": None,
        "sql_backend": None,
        "db_driver": None,
        "db_host": None,
        "db_listen_address": None,
        "db_database": None,
        "db_user": None,
        "db_password": None,
    }
    defaults.update(values)
    return argparse.Namespace(**defaults)


def context(env: dict[str, str] | None = None) -> GorakContext:
    return GorakContext(project=None, env=env or {})


def test_defaults_to_local_backend() -> None:
    connection = resolve_openroad_connection(
        args(vnode="myvnode", database="exampledb"),
        context(),
    )

    assert connection == OpenRoadConnection(
        backend="local",
        vnode="myvnode",
        database="exampledb",
        remote_host=None,
        sql_backend="local",
    )


def test_infers_remote_backend_from_remote_settings() -> None:
    connection = resolve_openroad_connection(
        args(
            user="test",
            host="windows-pc",
            gorak_root=r"C:\Development\gorak",
            vnode="myvnode",
            database="exampledb",
        ),
        context(),
    )

    assert connection == OpenRoadConnection(
        backend="remote",
        vnode="myvnode",
        database="exampledb",
        remote_host=RemoteHost(
            user="test",
            host="windows-pc",
            gorak_root=r"C:\Development\gorak",
        ),
        sql_backend="remote",
    )


def test_reads_settings_from_env() -> None:
    connection = resolve_openroad_connection(
        args(),
        context(
            {
                "GORAK_BACKEND": "remote",
                "GORAK_REMOTE_USER": "project-user",
                "GORAK_REMOTE_HOST": "project-host",
                "GORAK_REMOTE_ROOT": r"C:\Development\gorak",
                "GORAK_VNODE": "project-vnode",
                "GORAK_DATABASE": "project-db",
            }
        ),
    )

    assert connection == OpenRoadConnection(
        backend="remote",
        vnode="project-vnode",
        database="project-db",
        remote_host=RemoteHost(
            user="project-user",
            host="project-host",
            gorak_root=r"C:\Development\gorak",
        ),
        sql_backend="remote",
    )


def test_flags_override_env() -> None:
    connection = resolve_openroad_connection(
        args(
            user="flag-user",
            host="flag-host",
            gorak_root=r"C:\Flag\gorak",
            vnode="flag-vnode",
            database="flag-db",
        ),
        context(
            {
                "GORAK_BACKEND": "remote",
                "GORAK_REMOTE_USER": "project-user",
                "GORAK_REMOTE_HOST": "project-host",
                "GORAK_REMOTE_ROOT": r"C:\Development\gorak",
                "GORAK_VNODE": "project-vnode",
                "GORAK_DATABASE": "project-db",
            }
        ),
    )

    assert connection == OpenRoadConnection(
        backend="remote",
        vnode="flag-vnode",
        database="flag-db",
        remote_host=RemoteHost(
            user="flag-user",
            host="flag-host",
            gorak_root=r"C:\Flag\gorak",
        ),
        sql_backend="remote",
    )


def test_explicit_local_backend_ignores_remote_env() -> None:
    connection = resolve_openroad_connection(
        args(),
        context(
            {
                "GORAK_BACKEND": "local",
                "GORAK_REMOTE_USER": "project-user",
                "GORAK_REMOTE_HOST": "project-host",
                "GORAK_REMOTE_ROOT": r"C:\Development\gorak",
                "GORAK_VNODE": "project-vnode",
                "GORAK_DATABASE": "project-db",
            }
        ),
    )

    assert connection == OpenRoadConnection(
        backend="local",
        vnode="project-vnode",
        database="project-db",
        remote_host=None,
        sql_backend="local",
    )


def test_resolves_odbc_sql_backend_from_env() -> None:
    connection = resolve_openroad_connection(
        args(),
        context(
            {
                "GORAK_BACKEND": "remote",
                "GORAK_REMOTE_USER": "project-user",
                "GORAK_REMOTE_HOST": "project-host",
                "GORAK_REMOTE_ROOT": r"C:\Development\gorak",
                "GORAK_VNODE": "project-vnode",
                "GORAK_DATABASE": "project-db",
                "GORAK_SQL_BACKEND": "odbc",
                "GORAK_DB_DRIVER": "Ingres AC",
                "GORAK_DB_HOST": "db-host.example",
                "GORAK_DB_LISTEN_ADDRESS": "II7",
                "GORAK_DB_DATABASE": "source_db",
                "GORAK_DB_USER": "ingres",
                "GORAK_DB_PASSWORD": "secret",
            }
        ),
    )

    assert connection.sql_backend == "odbc"
    assert connection.odbc_settings == OdbcSettings(
        driver="Ingres AC",
        host="db-host.example",
        listen_address="II7",
        database="source_db",
        user="ingres",
        password="secret",
    )


def test_odbc_database_defaults_to_openroad_database() -> None:
    connection = resolve_openroad_connection(
        args(),
        context(
            {
                "GORAK_VNODE": "project-vnode",
                "GORAK_DATABASE": "project-db",
                "GORAK_SQL_BACKEND": "odbc",
                "GORAK_DB_DRIVER": "Ingres AC",
                "GORAK_DB_HOST": "db-host.example",
                "GORAK_DB_LISTEN_ADDRESS": "II7",
                "GORAK_DB_USER": "ingres",
                "GORAK_DB_PASSWORD": "secret",
            }
        ),
    )

    assert require_odbc_settings(connection).database == "project-db"


def test_errors_for_unsupported_sql_backend() -> None:
    with pytest.raises(ProjectError, match="SQL backend is not implemented"):
        resolve_openroad_connection(
            args(),
            context(
                {
                    "GORAK_VNODE": "project-vnode",
                    "GORAK_DATABASE": "project-db",
                    "GORAK_SQL_BACKEND": "unsupported",
                }
            ),
        )


def test_remote_sql_backend_requires_remote_settings() -> None:
    with pytest.raises(ProjectError, match="--user/GORAK_REMOTE_USER"):
        resolve_openroad_connection(
            args(),
            context(
                {
                    "GORAK_BACKEND": "local",
                    "GORAK_VNODE": "project-vnode",
                    "GORAK_DATABASE": "project-db",
                    "GORAK_SQL_BACKEND": "remote",
                }
            ),
        )


def test_errors_when_odbc_settings_are_missing() -> None:
    with pytest.raises(ProjectError, match="--db-host/GORAK_DB_HOST"):
        resolve_openroad_connection(
            args(),
            context(
                {
                    "GORAK_VNODE": "project-vnode",
                    "GORAK_DATABASE": "project-db",
                    "GORAK_SQL_BACKEND": "odbc",
                    "GORAK_DB_DRIVER": "Ingres AC",
                }
            ),
        )


def test_errors_for_unsupported_backend() -> None:
    with pytest.raises(ProjectError, match="OpenROAD backend is not implemented"):
        resolve_openroad_connection(
            args(),
            context({"GORAK_BACKEND": "unsupported"}),
        )


def test_errors_when_database_settings_are_missing() -> None:
    with pytest.raises(ProjectError, match="--vnode/GORAK_VNODE"):
        resolve_openroad_connection(args(), context())


def test_resolve_remote_host_reads_env() -> None:
    assert resolve_remote_host(
        args(),
        context(
            {
                "GORAK_REMOTE_USER": "project-user",
                "GORAK_REMOTE_HOST": "project-host",
                "GORAK_REMOTE_ROOT": r"C:\Development\gorak",
            }
        ),
    ) == RemoteHost(
        user="project-user",
        host="project-host",
        gorak_root=r"C:\Development\gorak",
    )


def test_resolve_remote_host_errors_when_settings_are_missing() -> None:
    with pytest.raises(ProjectError, match="--user/GORAK_REMOTE_USER"):
        resolve_remote_host(args(), context())


def test_require_remote_host_errors_for_local_connection() -> None:
    with pytest.raises(ProjectError, match="Remote host is required"):
        require_remote_host(
            OpenRoadConnection(
                backend="local",
                vnode="myvnode",
                database="exampledb",
                remote_host=None,
            )
        )


def test_require_odbc_settings_errors_for_non_odbc_connection() -> None:
    with pytest.raises(ProjectError, match="ODBC settings are required"):
        require_odbc_settings(
            OpenRoadConnection(
                backend="local",
                vnode="myvnode",
                database="exampledb",
                remote_host=None,
                sql_backend="local",
            )
        )


def test_connection_source_describes_local_and_remote() -> None:
    remote = RemoteHost("test", "windows-pc", r"C:\Development\gorak")
    assert (
        connection_source(OpenRoadConnection("remote", "myvnode", "exampledb", remote))
        == "remote host test@windows-pc"
    )
    assert (
        connection_source(OpenRoadConnection("local", "myvnode", "exampledb", None))
        == "local"
    )

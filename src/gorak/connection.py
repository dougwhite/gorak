import argparse
from dataclasses import dataclass
from typing import Literal, cast

from .project import GorakContext, ProjectError
from .remote import RemoteHost

Backend = Literal["local", "remote"]


@dataclass(frozen=True)
class OpenRoadConnection:
    backend: Backend
    vnode: str
    database: str
    remote_host: RemoteHost | None


def resolve_openroad_connection(
    args: argparse.Namespace, context: GorakContext
) -> OpenRoadConnection:
    env = context.env
    backend = resolve_backend(args, env)

    openroad_values = {
        "vnode": env_value(args, "vnode", env, "GORAK_VNODE"),
        "database": env_value(args, "database", env, "GORAK_DATABASE"),
    }
    missing = [key for key, value in openroad_values.items() if value is None]
    if backend == "remote":
        remote_values = remote_host_values(args, env)
        missing.extend(key for key, value in remote_values.items() if value is None)
    else:
        remote_values = {"user": None, "host": None, "gorak_root": None}

    if missing:
        raise ProjectError(
            "Missing OpenROAD connection settings: "
            + ", ".join(connection_hint(key) for key in missing)
        )

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
            if backend == "remote"
            else None
        ),
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
    hints = {
        "user": "--user/GORAK_REMOTE_USER",
        "host": "--host/GORAK_REMOTE_HOST",
        "gorak_root": "--gorak-root/GORAK_REMOTE_ROOT",
        "vnode": "--vnode/GORAK_VNODE",
        "database": "--database/GORAK_DATABASE",
    }
    return hints[key]


def require_remote_host(connection: OpenRoadConnection) -> RemoteHost:
    if connection.remote_host is None:
        raise ProjectError("Remote host is required for remote OpenROAD backend")
    return connection.remote_host


def connection_source(connection: OpenRoadConnection) -> str:
    if connection.backend == "local":
        return "local"
    return f"remote host {require_remote_host(connection).ssh_target}"

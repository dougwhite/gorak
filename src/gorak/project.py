"""Gorak project discovery, scaffolding, and local configuration."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from dotenv import dotenv_values, set_key, unset_key

PROJECT_MANIFEST = "gorak.json"
DEFAULT_VERSION = "0.1.0"
DEFAULT_STARTING_COMPONENT = "p4_init"
TEMPLATE_PACKAGE = "gorak.templates"
RunCommand = Callable[[list[str], Path], None]

ENV_EXAMPLE = """GORAK_BACKEND=local
GORAK_VNODE=myvnode
GORAK_DATABASE=exampledb

# Optional: use direct ODBC for read-only list commands.
# Requires a configured Actian Ingres ODBC client/driver on this machine.
# GORAK_SQL_BACKEND=odbc
# GORAK_DB_DRIVER=Ingres AC
# GORAK_DB_HOST=db-host.example
# GORAK_DB_LISTEN_ADDRESS=II7
# GORAK_DB_USER=ingres
# GORAK_DB_PASSWORD=secret
"""

DEFAULT_P4_INIT = """[proc4glsource]
datatype = "integer"

===

PROCEDURE p4_init
(

) =
DECLARE
ENDDECLARE
{
    CurProcedure.Trace(text = 'Hello World!');
    RETURN ER_OK;
}"""


class ProjectError(RuntimeError):
    """Raised when a gorak project operation fails."""


@dataclass(frozen=True)
class GorakProject:
    root: Path
    name: str


@dataclass(frozen=True)
class GorakContext:
    project: GorakProject | None
    env: dict[str, str]


def create_project(
    path: Path,
    run_cmd: RunCommand | None = None,
    init_repo: bool = True,
) -> GorakProject:
    root = path.resolve()
    manifest_path = root / PROJECT_MANIFEST

    if manifest_path.exists():
        raise ProjectError(f"Gorak project already exists: {root}")

    if root.exists() and any(root.iterdir()):
        raise ProjectError(f"Project directory must be empty: {root}")

    root.mkdir(parents=True, exist_ok=True)
    write_project_skeleton(root, root.name)
    if init_repo:
        init_git(root, run_cmd or run_subprocess)

    return load_project(root)


def run_subprocess(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def init_git(root: Path, run_cmd: RunCommand) -> None:
    try:
        run_cmd(["git", "init"], root)
    except subprocess.CalledProcessError as ex:
        print(
            f"WARNING: git init failed with exit code {ex.returncode}", file=sys.stderr
        )


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent

    for directory in [current, *current.parents]:
        if (directory / PROJECT_MANIFEST).is_file():
            return directory

    raise ProjectError(f"No gorak project found from: {start}")


def find_project_root_or_none(start: Path) -> Path | None:
    try:
        return find_project_root(start)
    except ProjectError:
        return None


def load_project(start: Path) -> GorakProject:
    root = find_project_root(start)
    manifest = read_json(root / PROJECT_MANIFEST)
    name = cast(str, manifest["name"])

    return GorakProject(root=root, name=name)


def load_context(start: Path) -> GorakContext:
    """Load project and local environment context for a path."""

    root = find_project_root_or_none(start)
    if root is None:
        return GorakContext(project=None, env=read_process_env())

    project = load_project(root)
    env = read_project_env(root)
    env.update(read_process_env())

    return GorakContext(project=project, env=env)


def read_process_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key.startswith("GORAK_")}


def read_project_env(root: Path) -> dict[str, str]:
    values = dotenv_values(root / ".env")
    return {key: value for key, value in values.items() if value is not None}


def write_project_skeleton(root: Path, name: str) -> None:
    app_dir = root / name
    app_dir.mkdir()

    write_json(
        root / PROJECT_MANIFEST,
        {
            "name": name,
            "version": DEFAULT_VERSION,
            "description": "An example gorak project",
            "author": "Your Name",
            "contact": "your.name@example.com",
            "license": "MIT",
        },
    )
    write_json(
        app_dir / "app.json",
        {
            "starting_component": DEFAULT_STARTING_COMPONENT,
            "description": "An example OpenROAD application",
            "included_applications": [],
        },
    )
    (app_dir / f"{DEFAULT_STARTING_COMPONENT}.w4gl").write_text(DEFAULT_P4_INIT)
    (root / "field_defaults.json").write_text(default_field_defaults_json())
    (root / ".env.example").write_text(ENV_EXAMPLE)
    (root / ".gitignore").write_text(".env\n.openroad/\n")


def default_field_defaults_json() -> str:
    """Read the packaged standard OpenROAD field defaults."""

    return files(TEMPLATE_PACKAGE).joinpath("field_defaults.json").read_text()


def read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text()))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=4) + "\n")


CONFIG_KEYS = [
    "GORAK_BACKEND",
    "GORAK_SQL_BACKEND",
    "GORAK_REMOTE_HOST",
    "GORAK_REMOTE_USER",
    "GORAK_REMOTE_ROOT",
    "GORAK_VNODE",
    "GORAK_DATABASE",
    "GORAK_DB_DRIVER",
    "GORAK_DB_HOST",
    "GORAK_DB_LISTEN_ADDRESS",
    "GORAK_DB_DATABASE",
    "GORAK_DB_USER",
    "GORAK_DB_PASSWORD",
]


def configure_project(
    project: GorakProject,
    backend: str,
    vnode: str,
    database: str,
    host: str | None = None,
    user: str | None = None,
    gorak_root: str | None = None,
    sql_backend: str | None = None,
    db_driver: str | None = None,
    db_host: str | None = None,
    db_listen_address: str | None = None,
    db_database: str | None = None,
    db_user: str | None = None,
    db_password: str | None = None,
) -> Path:
    """Write a complete .env connection shape for the selected backends."""

    env_path = project.root / ".env"
    env_path.touch(exist_ok=True)

    values = {
        "GORAK_BACKEND": backend,
        "GORAK_SQL_BACKEND": sql_backend,
        "GORAK_REMOTE_HOST": host,
        "GORAK_REMOTE_USER": user,
        "GORAK_REMOTE_ROOT": gorak_root,
        "GORAK_VNODE": vnode,
        "GORAK_DATABASE": database,
        "GORAK_DB_DRIVER": db_driver,
        "GORAK_DB_HOST": db_host,
        "GORAK_DB_LISTEN_ADDRESS": db_listen_address,
        "GORAK_DB_DATABASE": db_database,
        "GORAK_DB_USER": db_user,
        "GORAK_DB_PASSWORD": db_password,
    }

    for key in CONFIG_KEYS:
        value = values[key]
        if value is None:
            unset_key(env_path, key)
        else:
            set_key(env_path, key, value)

    return env_path


def configure_remote(
    project: GorakProject,
    host: str,
    user: str,
    gorak_root: str,
    vnode: str,
    database: str,
) -> Path:
    return configure_project(
        project=project,
        backend="remote",
        host=host,
        user=user,
        gorak_root=gorak_root,
        vnode=vnode,
        database=database,
    )

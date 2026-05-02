import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from dotenv import set_key

PROJECT_MANIFEST = "gorak.json"
DEFAULT_VERSION = "0.1.0"
DEFAULT_STARTING_COMPONENT = "p4_init"
RunCommand = Callable[[list[str], Path], None]

ENV_EXAMPLE = """GORAK_BACKEND=remote
GORAK_REMOTE_HOST=windows-pc
GORAK_REMOTE_USER=test
GORAK_REMOTE_ROOT=C:\\Development\\gorak
GORAK_VNODE=myvnode
GORAK_DATABASE=exampledb
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


def create_project(path: Path, run_cmd: RunCommand | None = None) -> GorakProject:
    root = path.resolve()
    manifest_path = root / PROJECT_MANIFEST

    if manifest_path.exists():
        raise ProjectError(f"Gorak project already exists: {root}")

    if root.exists() and any(root.iterdir()):
        raise ProjectError(f"Project directory must be empty: {root}")

    root.mkdir(parents=True, exist_ok=True)
    write_project_skeleton(root, root.name)
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


def load_project(start: Path) -> GorakProject:
    root = find_project_root(start)
    manifest = read_json(root / PROJECT_MANIFEST)
    name = cast(str, manifest["name"])

    return GorakProject(root=root, name=name)


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
            "included_applications": [],
        },
    )
    (app_dir / f"{DEFAULT_STARTING_COMPONENT}.w4gl").write_text(DEFAULT_P4_INIT)
    (root / ".env.example").write_text(ENV_EXAMPLE)
    (root / ".gitignore").write_text(".env\n.openroad/\n")


def read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text()))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=4) + "\n")


def configure_remote(
    project: GorakProject,
    host: str,
    user: str,
    gorak_root: str,
    vnode: str,
    database: str,
) -> Path:
    env_path = project.root / ".env"
    env_path.touch(exist_ok=True)

    values = {
        "GORAK_BACKEND": "remote",
        "GORAK_REMOTE_HOST": host,
        "GORAK_REMOTE_USER": user,
        "GORAK_REMOTE_ROOT": gorak_root,
        "GORAK_VNODE": vnode,
        "GORAK_DATABASE": database,
    }

    for key, value in values.items():
        set_key(env_path, key, value)

    return env_path

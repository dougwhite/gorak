import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

PROJECT_MANIFEST = "gorak.json"
DEFAULT_VERSION = "0.1.0"
DEFAULT_STARTING_COMPONENT = "p4_init"

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


def create_project(path: Path) -> GorakProject:
    root = path.resolve()
    manifest_path = root / PROJECT_MANIFEST

    if manifest_path.exists():
        raise ProjectError(f"Gorak project already exists: {root}")

    if root.exists() and any(root.iterdir()):
        raise ProjectError(f"Project directory must be empty: {root}")

    root.mkdir(parents=True, exist_ok=True)
    write_project_skeleton(root, root.name)

    return load_project(root)


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


def read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text()))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=4) + "\n")

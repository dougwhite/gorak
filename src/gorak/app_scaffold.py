"""Create disk-only application scaffolds inside existing Gorak projects."""

import re
from pathlib import Path
from uuid import uuid4

from .project import PROJECT_MANIFEST, GorakProject, ProjectError, read_json, write_json


def create_application(project: GorakProject, name: str, test: bool = False) -> Path:
    """Create an empty app and optionally register it without choosing a framework."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", name):
        raise ProjectError(
            "Application name must be an identifier of at most 32 characters"
        )
    root = project.root
    if any(p.name.casefold() == name.casefold() for p in root.iterdir()):
        raise ProjectError(f"Application path already exists: {name}")
    manifest = read_json(root / PROJECT_MANIFEST)
    changed = False
    if test:
        entries = manifest.get("tests", [])
        if not isinstance(entries, list):
            raise ProjectError("gorak.json tests must be an array")
        names = []
        for entry in entries:
            app = (
                entry
                if isinstance(entry, str)
                else entry.get("application")
                if isinstance(entry, dict)
                else None
            )
            if not isinstance(app, str) or not app:
                raise ProjectError("Each existing test entry must name an application")
            names.append(app.casefold())
        if name.casefold() not in names:
            manifest["tests"] = [*entries, {"application": name}]
            changed = True
    directory = root / name
    staged_manifest = root / f".gorak-manifest-{uuid4().hex}.json"
    directory.mkdir()
    try:
        write_json(
            directory / "app.json",
            {"starting_component": "", "description": "", "included_applications": []},
        )
        if changed:
            write_json(staged_manifest, manifest)
            staged_manifest.replace(root / PROJECT_MANIFEST)
    except OSError as ex:
        (directory / "app.json").unlink(missing_ok=True)
        directory.rmdir()
        raise ProjectError(f"Could not create application: {ex}") from ex
    finally:
        staged_manifest.unlink(missing_ok=True)
    return directory

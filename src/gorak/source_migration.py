"""Local, verified conversion of legacy projections to complete readable source."""

import json
from pathlib import Path
from uuid import uuid4

from .errors import ProjectError
from .importer import signature
from .portable_source import DIRECTORY, legacy_application, legacy_component
from .project import read_json
from .project_lock import project_lock
from .readable_source import (
    decode_application,
    decode_component,
    encode_application,
    encode_component,
    is_complete,
)
from .safe_pull import apply_files, fingerprint


def migrate_source(root: Path) -> Path | None:
    """Preserve readable edits and before-images; never change the database baseline."""
    with project_lock(root, "migrate-source"):
        if (root / ".openroad/revision-quarantine.json").exists():
            raise ProjectError("Resolve revision quarantine before migrating source")
        snapshot = fingerprint(root)
        operation = root / ".openroad/migrations" / uuid4().hex
        stage = operation / "stage"
        changes: dict[Path, bytes | None] = {}
        for app_file in sorted(root.glob("*/app.json")):
            folder = app_file.parent
            if folder.name.startswith("."):
                continue
            target = stage / folder.name
            target.mkdir(parents=True, exist_ok=True)
            if read_json(app_file).get("source_format") != 2:
                node = legacy_application(folder)
                content = (
                    json.dumps(encode_application(node), indent=4) + "\n"
                ).encode()
                (target / "app.json").write_bytes(content)
                if signature(decode_application(target)) != signature(node):
                    raise ProjectError("Application migration verification failed")
                changes[app_file] = content
            for path in sorted(folder.glob("*.w4gl")):
                if is_complete(path):
                    continue
                node = legacy_component(path)
                text, markup = encode_component(node)
                destination = target / path.name
                destination.write_text(text, encoding="utf-8", newline="\n")
                if markup is not None:
                    destination.with_suffix(".wml").write_text(
                        markup, encoding="utf-8", newline="\n"
                    )
                if signature(decode_component(destination)) != signature(node):
                    raise ProjectError(
                        f"Component migration verification failed: {path.name}"
                    )
                changes[path] = text.encode()
                if markup is not None:
                    changes[path.with_suffix(".wml")] = markup.encode()
            companion = folder / DIRECTORY
            for path in companion.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(companion)
                    if relative.as_posix() not in {
                        "format",
                        "application.xml",
                    } and not (
                        len(relative.parts) == 2
                        and relative.parts[0] == "components"
                        and path.suffix == ".xml"
                    ):
                        raise ProjectError(
                            f"Unrecognized file in legacy source directory: {relative}"
                        )
                    if (
                        path.parent.name == "components"
                        and not (folder / f"{path.stem}.w4gl").is_file()
                    ):
                        raise ProjectError(
                            "Orphaned companion: restore its readable component before migration"
                        )
                    changes[path] = None
            defaults = folder / "field_defaults.json"
            if defaults.is_file():
                changes[defaults] = None
        if not changes:
            return None
        defaults = root / "field_defaults.json"
        if defaults.is_file():
            changes[defaults] = None
        if fingerprint(root) != snapshot:
            raise ProjectError("Source changed during migration; no files installed")
        marker = root / ".openroad/pull-pending.json"
        marker.write_text(
            json.dumps({"operation": str(operation), "kind": "source-migration"})
        )
        apply_files(root, changes, operation, snapshot)
        (operation / "verified").write_text(
            "Readable source reconstruction verified before installation\n"
        )
        marker.unlink()
        for app_file in root.glob("*/app.json"):
            directory = app_file.parent / DIRECTORY
            if directory.is_dir():
                for child in sorted(
                    directory.rglob("*"), key=lambda p: len(p.parts), reverse=True
                ):
                    if child.is_dir() and not any(child.iterdir()):
                        child.rmdir()
                if not any(directory.iterdir()):
                    directory.rmdir()
        return operation

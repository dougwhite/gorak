"""Local, verified conversion to the established compact source contract."""

import json
from pathlib import Path
from shutil import copy2
from uuid import uuid4

from lxml import etree

from .contract_source import decode_component
from .errors import ProjectError
from .export import application_metadata, apply_field_default_inheritance
from .parser import encode_w4gl, parse_application_xml, parse_component_node
from .portable_source import DIRECTORY, legacy_application, legacy_component
from .project import read_json
from .project_lock import project_lock
from .safe_pull import apply_files, fingerprint
from .xml_writer import document


def migrate_source(root: Path) -> Path | None:
    """Preserve readable edits and before-images; never change the database baseline."""
    with project_lock(root, "migrate-source"):
        if (root / ".openroad/revision-quarantine.json").exists():
            raise ProjectError("Resolve revision quarantine before migrating source")
        snapshot = fingerprint(root)
        operation = root / ".openroad/migrations" / uuid4().hex
        stage = operation / "stage"
        changes: dict[Path, bytes | None] = {}
        stage.mkdir(parents=True)
        if (root / "field_defaults.json").is_file():
            copy_defaults(root / "field_defaults.json", stage / "field_defaults.json")
        for app_file in sorted(root.glob("*/app.json")):
            folder = app_file.parent
            if folder.name.startswith("."):
                continue
            target = stage / folder.name
            target.mkdir(parents=True, exist_ok=True)
            node = legacy_application(folder)
            app = parse_application_xml(etree.fromstring(document([node])))
            content = (
                json.dumps(
                    application_metadata(
                        app.application, included_applications=app.included_applications
                    ),
                    indent=4,
                )
                + "\n"
            ).encode()
            (target / "app.json").write_bytes(content)
            changes[app_file] = content
            if (folder / "field_defaults.json").is_file():
                copy_defaults(
                    folder / "field_defaults.json", target / "field_defaults.json"
                )
            sources = [
                (path, legacy_component(path)) for path in sorted(folder.glob("*.w4gl"))
            ]

            for path, node in sources:
                component = parse_component_node(node)
                apply_field_default_inheritance(stage, target.name, [component])
                text, markup = encode_w4gl(component), component.markup
                text = text.rstrip() + "\n"
                markup = markup.rstrip() + "\n" if markup is not None else None
                destination = target / path.name
                destination.write_text(text, encoding="utf-8", newline="\n")
                if markup is not None:
                    destination.with_suffix(".wml").write_text(
                        markup, encoding="utf-8", newline="\n"
                    )
                reconstructed = parse_component_node(decode_component(destination))
                apply_field_default_inheritance(stage, target.name, [reconstructed])
                if (
                    encode_w4gl(reconstructed).strip() != text.strip()
                    or (reconstructed.markup or "").strip() != (markup or "").strip()
                ):
                    raise ProjectError(
                        f"Component migration verification failed: {path.name}"
                    )
                changes[path] = text.encode()
                if markup is not None:
                    changes[path.with_suffix(".wml")] = markup.encode()
            if (target / "field_defaults.json").is_file():
                changes[folder / "field_defaults.json"] = (
                    target / "field_defaults.json"
                ).read_bytes()
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
        if (stage / "field_defaults.json").is_file():
            changes[root / "field_defaults.json"] = (
                stage / "field_defaults.json"
            ).read_bytes()
        changes = {
            p: data
            for p, data in changes.items()
            if (p.read_bytes() if p.exists() else None) != data
        }
        if not changes:
            return None
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


def copy_defaults(source: Path, destination: Path) -> None:
    """Remove preview-only transport metadata, retaining effective property values."""
    values = read_json(source)
    if "structure" not in values:
        copy2(source, destination)
        return
    from .field_defaults import parse_field_defaults_node
    from .palette import decode

    destination.write_text(
        json.dumps(parse_field_defaults_node(decode(values)), indent=4) + "\n"
    )

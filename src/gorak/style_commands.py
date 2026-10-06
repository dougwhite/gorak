"""Verified local stylesheet publication and promotion."""

import json
from pathlib import Path
from uuid import uuid4

from . import native_styles as styles
from .errors import ProjectError
from .project_lock import project_lock
from .safe_pull import apply_files, fingerprint


def encoded(value: styles.Json) -> bytes:
    return (json.dumps(value, indent=4) + "\n").encode("utf-8")


def describe(root: Path, app: str | None, component: str | None) -> styles.Json:
    from .importer import validate_name
    from .parser import FRAME_COMPONENT_TYPES, parse_w4gl

    if component and not app:
        raise ProjectError("--component requires --app")
    value = styles.project_styles(root)
    if app:
        validate_name(app)
        folder = root / app
        if not (folder / "app.json").is_file():
            raise ProjectError("Application source does not exist")
        value = styles.parent_styles(folder)
        if component:
            validate_name(component)
            source = folder / f"{component}.w4gl"
            if not source.is_file():
                raise ProjectError("Component source does not exist")
            if (
                parse_w4gl(source.read_text(), source.stem).type
                not in FRAME_COMPONENT_TYPES
            ):
                raise ProjectError("Only frames have native stylesheets")
            value = styles.frame_styles(source)
    return {
        "stylesheet": value,
        "entries": [] if value.get("absent") is True else styles.entries(value),
    }


def install(
    root: Path,
    changes: dict[Path, bytes | None],
    snapshot: dict[str, str],
    *,
    dry_run: bool,
) -> str:
    changes = {
        p: data
        for p, data in changes.items()
        if (p.read_bytes() if p.exists() else None) != data
    }
    if not changes:
        return "Stylesheets unchanged"
    plan = "\n".join(
        f"{'Remove' if data is None else 'Write'} {p.relative_to(root)}"
        for p, data in sorted(changes.items())
    )
    if not dry_run:
        if fingerprint(root) != snapshot:
            raise ProjectError("Project changed while preparing stylesheet changes")
        recovery = root / ".openroad/styles" / uuid4().hex
        recovery.mkdir(parents=True)
        marker = root / ".openroad/pull-pending.json"
        marker.write_text(
            json.dumps({"operation": str(recovery), "kind": "stylesheet-maintenance"})
        )
        apply_files(root, changes, recovery, snapshot)
        (recovery / "verified").write_text(
            "Resolved native stylesheets verified before installation\n"
        )
        marker.unlink()
    return plan


def maintain(root: Path, operation: str, *, dry_run: bool = False) -> str:
    with project_lock(root, f"styles-{operation}"):
        if (root / ".openroad/revision-quarantine.json").exists():
            raise ProjectError(
                "Resolve revision quarantine before stylesheet maintenance"
            )
        snapshot = fingerprint(root)
        project = styles.project_styles(root)
        changes: dict[Path, bytes | None] = {}
        if operation == "publish":
            # Complete mode makes baseline lookup unnecessary for every reader.
            changes[root / "field_defaults.json"] = encoded(styles.complete(project))
        elif operation == "compact":
            apps: dict[Path, styles.Json] = {}
            frames: dict[Path, styles.Json] = {}
            for manifest in sorted(root.glob("*/app.json")):
                folder = manifest.parent
                if folder.name.startswith("."):
                    continue
                apps[folder] = styles.parent_styles(folder)
                for source in sorted(folder.glob("*.w4gl")):
                    from .parser import FRAME_COMPONENT_TYPES, parse_w4gl

                    if (
                        parse_w4gl(source.read_text(), source.stem).type
                        not in FRAME_COMPONENT_TYPES
                    ):
                        continue
                    frames[source] = styles.frame_styles(source)
                children = [
                    value
                    for path, value in frames.items()
                    if path.parent == folder and value.get("absent") is not True
                ]
                if children and all(value == children[0] for value in children):
                    apps[folder] = children[0]
            values = list(apps.values())
            if values and all(value == values[0] for value in values):
                project = values[0]
            original = styles.read(root / "field_defaults.json")
            root_layer = (
                styles.complete(project)
                if original.get("standalone") is True
                else styles.difference(styles.baseline(), project)
            )
            changes[root / "field_defaults.json"] = encoded(root_layer)
            for folder, value in apps.items():
                delta = styles.difference(project, value)
                if styles.resolve(project, delta) != value:
                    raise ProjectError("Stylesheet compaction changed an application")
                changes[folder / "field_defaults.json"] = (
                    encoded(delta) if styles.has_overrides(delta) else None
                )
            for source, value in frames.items():
                parent = apps[source.parent]
                delta = (
                    value
                    if value.get("absent") is True
                    else styles.difference(parent, value)
                )
                if styles.resolve_frame(parent, delta) != value:
                    raise ProjectError("Stylesheet compaction changed a frame")
                changes[source.with_suffix(".fielddefaults.json")] = (
                    encoded(delta) if styles.has_overrides(delta) else None
                )
        else:
            raise ProjectError(f"Unknown stylesheet operation: {operation}")
        changes = externalize_changes(root, changes)
        return install(root, changes, snapshot, dry_run=dry_run)


def externalize_changes(
    root: Path, changes: dict[Path, bytes | None]
) -> dict[Path, bytes | None]:
    """Prepare stylesheet assets in isolation so dry runs and recovery stay safe."""
    from shutil import copy2
    from tempfile import TemporaryDirectory

    from .image_assets import AssetWriter, source_files, stylesheet_assets

    result = dict(changes)
    with TemporaryDirectory(prefix="gorak-style-assets-") as temporary:
        stage = Path(temporary)
        for folder in {path.parent for path in changes}:
            for asset in source_files(folder):
                if "images" not in asset.relative_to(folder).parts:
                    continue
                target = stage / asset.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                copy2(asset, target)
        writers: dict[Path, AssetWriter] = {}
        for path, content in changes.items():
            if content is None:
                continue
            folder = stage / path.parent.relative_to(root)
            if folder not in writers:
                writers[folder] = AssetWriter(folder, origins_from=path.parent)
            writer = writers[folder]
            projected = stylesheet_assets(
                json.loads(content), folder, exporting=True, _writer=writer
            )
            # Resolve the staged representation before installing any files.
            restored = stylesheet_assets(projected, folder, exporting=False)
            if canonical_bitmaps(restored) != canonical_bitmaps(json.loads(content)):
                raise ProjectError("Stylesheet asset conversion changed native data")
            result[path] = encoded(projected)
        for asset in stage.rglob("*"):
            if asset.is_file():
                result[root / asset.relative_to(stage)] = asset.read_bytes()
    return result


def canonical_bitmaps(value: object) -> object:
    from .bitmap_codec import normalized

    if isinstance(value, dict):
        return {
            key: normalized(item)
            if key == "obj_encoded" and isinstance(item, str)
            else canonical_bitmaps(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [canonical_bitmaps(item) for item in value]
    return value

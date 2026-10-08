"""Verified local stylesheet publication and promotion."""

import json
from collections.abc import Callable
from pathlib import Path
from shutil import rmtree
from time import monotonic
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
    retain_recovery: bool = True,
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
        if not retain_recovery:
            rmtree(recovery)
    return plan


class _Progress:
    def __init__(self, callback: Callable[[str], None] | None) -> None:
        self.callback = callback
        self.started = monotonic()
        self.phase_started = self.started
        self.last = 0.0
        self.phase = ""

    def update(self, phase: str, done: int = 0, total: int = 0) -> None:
        now = monotonic()
        changed = phase != self.phase
        if changed:
            self.phase, self.phase_started = phase, now
        if self.callback and (changed or done == total or now - self.last >= 1):
            elapsed = now - self.started
            eta = (
                f", phase ETA {(now - self.phase_started) * (total - done) / done:.0f}s"
                if done and total > done
                else ""
            )
            count = f" {done}/{total}" if total else ""
            self.callback(f"{phase}{count} — elapsed {elapsed:.0f}s{eta}")
            self.last = now


def maintain(
    root: Path,
    operation: str,
    *,
    dry_run: bool = False,
    progress: Callable[[str], None] | None = None,
) -> str:
    from .parser import FRAME_COMPONENT_TYPES, parse_w4gl
    from .style_compaction import ordered_key, promote
    from .style_values import difference, merge

    report = _Progress(progress)
    with project_lock(root, f"styles-{operation}"), styles.validation_scope():
        if (root / ".openroad/revision-quarantine.json").exists():
            raise ProjectError(
                "Resolve revision quarantine before stylesheet maintenance"
            )
        report.update("Checking source snapshot")
        snapshot = fingerprint(root)
        layers: dict[Path, styles.Json] = {}

        def read(path: Path) -> styles.Json:
            if path not in layers:
                layers[path] = styles.read(path)
            return layers[path]

        original = read(root / "field_defaults.json")
        stock = None if original.get("standalone") is True else styles.baseline()
        project = styles.resolve(stock, original)
        changes: dict[Path, bytes | None] = {}

        def propose(path: Path, value: styles.Json) -> None:
            # Compare resolved image references before staging or encoding assets.
            if (not value and path.exists()) or ordered_key(read(path)) != ordered_key(
                value
            ):
                changes[path] = encoded(value) if value else None

        def delta(parent: styles.Json, desired: styles.Json) -> styles.Json:
            value = difference(parent, desired)
            # Both inputs were validated on load/promotion. Exact ordered equality
            # proves the delta reconstructs that valid native sheet without another
            # XML decode/encode for every frame.
            if ordered_key(merge(parent, value)) != ordered_key(desired):
                raise ProjectError("Stylesheet compaction changed native data")
            return value

        if operation == "publish":
            propose(root / "field_defaults.json", styles.complete(project))
        elif operation == "compact":
            apps: dict[Path, styles.Json] = {}
            frames: dict[Path, styles.Json] = {}
            sources = {
                manifest.parent: sorted(manifest.parent.glob("*.w4gl"))
                for manifest in sorted(root.glob("*/app.json"))
                if not manifest.parent.name.startswith(".")
            }
            total = sum(map(len, sources.values()))
            done = 0
            report.update("Reading and promoting application styles", 0, total)
            for folder, paths in sources.items():
                parent = styles.resolve(project, read(folder / "field_defaults.json"))
                children: list[styles.Json] = []
                for source in paths:
                    if (
                        parse_w4gl(source.read_text(), source.stem).type
                        in FRAME_COMPONENT_TYPES
                    ):
                        layer = read(source.with_suffix(".fielddefaults.json"))
                        value = styles.resolve_frame(parent, layer) if layer else parent
                        frames[source] = value
                        children.append(value)
                    done += 1
                    report.update(
                        "Reading and promoting application styles", done, total
                    )
                apps[folder] = promote(children, parent)
            report.update("Promoting shared project rules")
            project = promote(list(apps.values()), project)
            root_layer = (
                styles.complete(project)
                if original.get("standalone") is True
                else delta(stock or styles.baseline(), project)
            )
            propose(root / "field_defaults.json", root_layer)
            total = len(apps) + len(frames)
            report.update("Verifying and trimming inherited rules", 0, total)
            for done, (folder, value) in enumerate(apps.items(), 1):
                propose(folder / "field_defaults.json", delta(project, value))
                report.update("Verifying and trimming inherited rules", done, total)
            for done, (source, value) in enumerate(frames.items(), len(apps) + 1):
                layer = (
                    value
                    if value.get("absent") is True
                    else delta(apps[source.parent], value)
                )
                propose(source.with_suffix(".fielddefaults.json"), layer)
                report.update("Verifying and trimming inherited rules", done, total)
        else:
            raise ProjectError(f"Unknown stylesheet operation: {operation}")
        report.update("Preparing and verifying image assets", 0, len(changes))
        changes = externalize_changes(root, changes, progress=report.update)
        report.update(
            "Installing verified styles" if not dry_run else "Finalizing dry run"
        )
        result = install(
            root,
            changes,
            snapshot,
            dry_run=dry_run,
            retain_recovery=operation != "compact",
        )
        report.update("Stylesheet maintenance complete")
        return result


def externalize_changes(
    root: Path,
    changes: dict[Path, bytes | None],
    *,
    progress: Callable[[str, int, int], None] | None = None,
) -> dict[Path, bytes | None]:
    """Prepare stylesheet assets in isolation so dry runs and recovery stay safe."""
    from shutil import copy2
    from tempfile import TemporaryDirectory

    from .image_assets import AssetWriter, source_files, stylesheet_assets
    from .style_compaction import ordered_key

    result = dict(changes)
    with TemporaryDirectory(prefix="gorak-style-assets-") as temporary:
        stage = Path(temporary)
        for folder in {
            path.parent for path, content in changes.items() if content is not None
        }:
            for asset in source_files(folder):
                if "images" not in asset.relative_to(folder).parts:
                    continue
                target = stage / asset.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                copy2(asset, target)
        writers: dict[Path, AssetWriter] = {}
        for index, (path, content) in enumerate(changes.items(), 1):
            if progress:
                progress("Preparing and verifying image assets", index, len(changes))
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
            if ordered_key(canonical_bitmaps(restored)) != ordered_key(
                canonical_bitmaps(json.loads(content))
            ):
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

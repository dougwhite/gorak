"""Verified local stylesheet publication, promotion, and native migration."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from . import native_styles as styles
from .errors import ProjectError
from .project_lock import project_lock
from .safe_pull import apply_files, fingerprint


def encoded(value: styles.Json) -> bytes:
    return (json.dumps(value, indent=4) + "\n").encode("utf-8")


def describe(root: Path, app: str | None, component: str | None) -> styles.Json:
    from .importer import validate_name
    from .parser import parse_w4gl

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
            if parse_w4gl(source.read_text(), source.stem).type != "framesource":
                raise ProjectError("Only frames have native stylesheets")
            if not styles.is_native_source(source):
                raise ProjectError(
                    "Migrate legacy frames before resolving native stylesheets"
                )
            value = styles.frame_styles(source)
    return {**styles.complete(value), "entries": styles.entries(value)}


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
                    from .parser import parse_w4gl

                    if (
                        parse_w4gl(source.read_text(), source.stem).type
                        != "framesource"
                    ):
                        continue
                    if not styles.is_native_source(source):
                        raise ProjectError(
                            "Migrate legacy frames before stylesheet compaction"
                        )
                    frames[source] = styles.frame_styles(source)
                children = [
                    value for path, value in frames.items() if path.parent == folder
                ]
                if children and all(value == children[0] for value in children):
                    apps[folder] = children[0]
            values = list(apps.values())
            if values and all(value == values[0] for value in values):
                project = values[0]
            original = styles.read(root / "field_defaults.json")
            root_layer = (
                styles.complete(project)
                if original["mode"] == "complete"
                else styles.difference(styles.baseline(), project)
            )
            changes[root / "field_defaults.json"] = encoded(root_layer)
            for folder, value in apps.items():
                delta = styles.difference(project, value)
                if styles.resolve(project, delta) != value:
                    raise ProjectError("Stylesheet compaction changed an application")
                changes[folder / "field_defaults.json"] = (
                    encoded(delta) if delta["changes"] else None
                )
            for source, value in frames.items():
                parent = apps[source.parent]
                delta = styles.difference(parent, value)
                if styles.resolve(parent, delta) != value:
                    raise ProjectError("Stylesheet compaction changed a frame")
                changes[source.with_suffix(".fielddefaults.json")] = (
                    encoded(delta) if delta["changes"] else None
                )
        else:
            raise ProjectError(f"Unknown stylesheet operation: {operation}")
        return install(root, changes, snapshot, dry_run=dry_run)


def migrate(root: Path, *, dry_run: bool = False) -> str:
    """Reproject proven native source; never interpret a legacy style as identity."""
    from lxml import etree

    from .component_defaults import encode_source_w4gl
    from .contract_source import decode_component, equivalent
    from .parser import (
        FRAME_MARKUP_CHILDREN,
        encode_frame_markup,
        parse_component_node,
        parse_w4gl,
    )
    from .portable_source import DIRECTORY, cached_node, read_document

    with project_lock(root, "styles-migrate"):
        if (root / ".openroad/revision-quarantine.json").exists():
            raise ProjectError(
                "Resolve revision quarantine before stylesheet maintenance"
            )
        snapshot = fingerprint(root)
        root_path = root / "field_defaults.json"
        if (
            root_path.exists()
            and json.loads(root_path.read_text()).get("schema") == styles.SCHEMA
        ):
            for source in root.glob("*/*.w4gl"):
                if parse_w4gl(source.read_text(), source.stem).type == "framesource":
                    if not styles.is_native_source(source):
                        raise ProjectError(
                            "Project mixes native stylesheets and legacy frames; re-export authoritative source"
                        )
                    styles.frame_styles(source)
            return "Stylesheets unchanged"
        parent = styles.baseline()
        expected: dict[Path, etree._Element] = {}
        changes: dict[Path, bytes | None] = {root_path: encoded(styles.empty_delta())}
        for manifest in sorted(root.glob("*/app.json")):
            folder = manifest.parent
            if folder.name.startswith("."):
                continue
            changes[folder / "field_defaults.json"] = None
            for source in sorted(folder.glob("*.w4gl")):
                if parse_w4gl(source.read_text(), source.stem).type != "framesource":
                    continue
                companion = folder / DIRECTORY / "components" / f"{source.stem}.xml"
                if companion.exists():
                    nodes = read_document(companion).findall("COMPONENT")
                    if len(nodes) != 1 or nodes[0].get("name") != source.stem:
                        raise ProjectError(f"Invalid native evidence for {source.name}")
                    node = nodes[0]
                else:
                    node = cached_node(folder, "COMPONENT", source.stem)
                if node is None:
                    raise ProjectError(
                        f"Authoritative native XML required for {source.name}; re-export first"
                    )
                # Refuse to overwrite locally changed or ambiguously compressed state.
                try:
                    matches = equivalent(node, decode_component(source))
                except (ProjectError, ValueError) as ex:
                    raise ProjectError(
                        f"Cannot prove legacy field state for {source.name}; re-export authoritative source"
                    ) from ex
                if not matches:
                    raise ProjectError(
                        f"Legacy source differs from native evidence for {source.name}; reconcile before migrating"
                    )
                expected[source] = node
                native = node.find("fielddefaults")
                if native is None:
                    native = etree.Element("fielddefaults")
                delta = styles.difference(parent, styles.encode(native))
                component = parse_component_node(node)
                component.props["fielddefaults"] = delta
                markup = encode_frame_markup(
                    [child for child in node if child.tag in FRAME_MARKUP_CHILDREN],
                    {},
                    explicit=True,
                )
                changes[source] = encode_source_w4gl(component).encode("utf-8")
                changes[source.with_suffix(".wml")] = markup.encode("utf-8")
                changes[source.with_suffix(".fielddefaults.json")] = (
                    encoded(delta) if delta["changes"] else None
                )
        with TemporaryDirectory(prefix="gorak-styles-") as temporary:
            stage = Path(temporary)
            for path, content in changes.items():
                if content is not None:
                    target = stage / path.relative_to(root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            for source, native in expected.items():
                restored = decode_component(stage / source.relative_to(root))
                if not equivalent(native, restored, exact_styles=True):
                    raise ProjectError(
                        f"Native source verification failed for {source.name}"
                    )
        return install(root, changes, snapshot, dry_run=dry_run)

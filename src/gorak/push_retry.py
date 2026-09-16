"""Reconcile interrupted source writes using retained XML, never compile status."""

import json
import os
from pathlib import Path
from uuid import uuid4

from lxml import etree

from .connection import OpenRoadConnection
from .errors import PostPushCompilationError, ProjectError
from .export import backup_application_xml, read_applications
from .importer import signature, validate_name
from .portable_source import read_document
from .safe_pull import apply_files, fingerprint
from .sync_plan import baseline_inventory, xml_inventory
from .xml_writer import document


def write_record(path: Path, value: object) -> None:
    staged = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        with staged.open("w") as handle:
            handle.write(json.dumps(value, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def pending_operation(root: Path) -> Path | None:
    marker = root / ".openroad/push-pending.json"
    if not marker.exists():
        return None
    try:
        record = json.loads(marker.read_text())
        operation = Path(record["operation"]).resolve()
        if (
            operation.parent != (root / ".openroad/pushes").resolve()
            or not operation.is_dir()
        ):
            raise ValueError("invalid operation path")
        if record.get("state") == "recovery_required":
            raise ProjectError(
                "Source tracking requires recovery: choose `gorak recover push --take disk` or `--take database` (disk is also `gorak sync --push --force`)"
            )
        return operation
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as ex:
        raise ProjectError(
            "Invalid pending push record; use explicit recovery or push --force"
        ) from ex


def mark_recovery(root: Path, operation: Path) -> None:
    write_record(
        root / ".openroad/push-pending.json",
        {"operation": str(operation), "state": "recovery_required"},
    )


def submitted_inventory(operation: Path, root: Path) -> dict[str, etree._Element]:
    """Read this attempt's preflight payloads; support retained v8 operation plans."""
    try:
        plan = json.loads((operation / "plan.json").read_text())
        result: dict[str, etree._Element] = {}
        for index, key in enumerate(plan["creations_or_updates"]):
            app = key.split("/")[0]
            validate_name(app)
            for node in read_document(operation / f"{index}-submitted.xml"):
                name = str(node.get("name", ""))
                validate_name(name)
                result[
                    app.casefold()
                    if node.tag == "APPLICATION"
                    else f"{app}/{name}".casefold()
                ] = node
        for app, name in plan["script_updates"]:
            validate_name(app)
            validate_name(name)
            retained = operation / "submitted" / app / f"{name}.xml"
            if retained.is_file():
                paths = [retained]
            else:
                # v8 retained submitted payloads in per-import artifacts only.
                paths = sorted(
                    (root / ".openroad/imports").glob("*/submitted.xml"),
                    key=lambda p: p.stat().st_mtime_ns,
                )
            for path in paths:
                for node in read_document(path).findall("COMPONENT"):
                    if node.get("name") == name:
                        if path != retained:
                            source = path.parent / "source.w4gl"
                            baseline = path.parent / "baseline.xml"
                            # Only artifacts with an identifiable application baseline.
                            if not source.is_file() or not baseline.is_file():
                                continue
                            base = read_document(baseline).find("APPLICATION")
                            if base is None or base.get("name") != app:
                                continue
                        result[f"{app}/{name}".casefold()] = node
        return result
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OSError,
        etree.XMLSyntaxError,
    ) as ex:
        raise ProjectError(
            "Cannot read interrupted push evidence; choose explicit recovery or push --force"
        ) from ex


def prepare_tracking(
    connection: OpenRoadConnection, root: Path, *, force: bool = False
) -> Path | None:
    """Refresh only proven prior imports, or snapshot database under explicit disk authority.

    Called with the checkout mutation lock held. Source files are never changed.
    Force retains old tracking and current database XML before replacing baselines.
    """
    from .sync_guard import binding_status

    marker = root / ".openroad/push-pending.json"
    if not force and not marker.exists():
        return None
    if (
        binding_status(connection, root, recover_push=True, recover_pull=force)
        != "verified"
    ):
        raise ProjectError("Retry/recovery requires a verified target binding")
    from .sync_guard import validate_tracking_health

    validate_tracking_health(connection, root)
    previous = None if force else pending_operation(root)
    submitted = submitted_inventory(previous, root) if previous else {}
    initial = fingerprint(root)
    if force:
        names = {p.parent.name for p in root.glob("*/app.json")}
        names.update(
            p.name
            for p in (root / ".openroad").iterdir()
            if p.is_dir() and list(p.glob("*.xml"))
        )
        tracking = root / ".openroad/tracked-applications.json"
        if tracking.exists():
            try:
                tracked = json.loads(tracking.read_text())
                if isinstance(tracked, list) and all(
                    isinstance(n, str) for n in tracked
                ):
                    names.update(tracked)
            except ValueError:
                pass  # Explicit force preserves and replaces the damaged record.
        baseline: dict[str, object] = {}
    else:
        baseline_root = previous / "baseline" if previous is not None else root
        if not (baseline_root / ".openroad").is_dir():
            baseline_root = root
        baseline, names = baseline_inventory(baseline_root)
        names |= {key.split("/")[0] for key in submitted}
    for name in names:
        validate_name(name)
    operation = (
        root / ".openroad/pushes" / f"{'force' if force else 'retry'}-{uuid4().hex}"
    )
    operation.mkdir(parents=True)
    if marker.exists():
        (operation / "previous-marker.json").write_bytes(marker.read_bytes())
    pull_marker = root / ".openroad/pull-pending.json"
    if pull_marker.exists():
        (operation / "previous-pull-marker.json").write_bytes(pull_marker.read_bytes())
    (operation / "source").mkdir()
    # Preserve readable source even when later reconciliation explicitly takes DB.
    for folder in root.glob("*/app.json"):
        for path in folder.parent.iterdir():
            if path.is_file() and (
                path.suffix in {".w4gl", ".wml"}
                or path.name in {"app.json", "field_defaults.json"}
            ):
                copy = operation / "source" / path.relative_to(root)
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_bytes(path.read_bytes())
    defaults = root / "field_defaults.json"
    if defaults.exists():
        (operation / "source/field_defaults.json").write_bytes(defaults.read_bytes())
    available = {a.name.casefold(): a.name for a in read_applications(connection)}
    changes: dict[Path, bytes | None] = {}
    exports: dict[str, Path] = {}
    for app in sorted(names):
        if app.casefold() in available and app != available[app.casefold()]:
            raise ProjectError(f"Application casing changed: {app}")
        cache = root / ".openroad" / app
        if force:
            changes.update({p: None for p in cache.glob("*.xml")})
        if app.casefold() not in available:
            continue
        exported = operation / f"{app}.xml"
        backup_application_xml(connection, app, exported)
        exports[app] = exported
        tree = read_document(exported)
        apps = tree.findall("APPLICATION")
        if (
            tree.tag != "OPENROAD"
            or len(apps) != 1
            or apps[0].get("name") != app
            or any(n.tag not in {"APPLICATION", "COMPONENT"} for n in tree)
        ):
            raise ProjectError(
                f"Invalid application export while reconciling {app}; baselines unchanged"
            )
        for node in tree:
            validate_name(str(node.get("name", "")))
        actual = xml_inventory(tree, app)
        if force:
            changes[cache / f"{app}.xml"] = exported.read_bytes()
            continue
        accepted = set()
        for node in tree:
            key = (
                app.casefold()
                if node.tag == "APPLICATION"
                else f"{app}/{node.get('name')}".casefold()
            )
            if actual[key] == baseline.get(key):
                accepted.add(key)
            elif key in submitted:
                from .frame_geometry import geometry_signature

                if geometry_signature(node) == geometry_signature(submitted[key]):
                    accepted.add(key)
                    if node.tag == "COMPONENT":
                        changes[cache / f"{node.get('name')}.xml"] = document([node])
        # A full baseline must not hide independent edits or deletions.
        old_keys = {
            k
            for k in baseline
            if k == app.casefold() or k.startswith(app.casefold() + "/")
        }
        if accepted == set(actual) and old_keys <= actual.keys():
            changes.update({p: None for p in cache.glob("*.xml")})
            changes[cache / f"{app}.xml"] = exported.read_bytes()
    # Revalidate the database before publishing even a recovered baseline.
    for app, exported in exports.items():
        check = operation / f"{app}-verify.xml"
        backup_application_xml(connection, app, check)
        if signature(read_document(check)) != signature(read_document(exported)):
            raise ProjectError("Database changed while reconciling push; retry")
    if fingerprint(root) != initial:
        raise ProjectError("Project changed while reconciling push; retry")
    if force:
        changes[root / ".openroad/tracked-applications.json"] = (
            json.dumps(sorted(names)) + "\n"
        ).encode()
    changes = {
        p: data
        for p, data in changes.items()
        if (p.read_bytes() if p.exists() else None) != data
    }
    if force:
        mark_recovery(root, operation)
        pull_marker.unlink(missing_ok=True)
    try:
        apply_files(root, changes, operation, initial)
    except Exception:
        mark_recovery(root, operation)
        raise
    (operation / "verified").write_text(
        "Database snapshot verified; displaced source and tracking retained\n"
    )
    if not force:
        from .compiler import queue_compilation

        queue_compilation(
            root,
            [
                (key.split("/", 1)[0], key.split("/", 1)[1])
                for key in submitted
                if "/" in key
            ],
        )
        marker.unlink()
    return operation


def finish_forced_push(
    connection: OpenRoadConnection, root: Path, operation: Path
) -> str:
    """Complete disk authority after its snapshot, with the checkout lock held."""
    from .push import push_project

    marker = root / ".openroad/push-pending.json"
    marker.unlink(missing_ok=True)
    compilation_error: PostPushCompilationError | None = None
    try:
        try:
            result = push_project(connection, root)
        except PostPushCompilationError as ex:
            # The source push is already committed. Complete authority recovery
            # before propagating the separate compilation failure to the CLI.
            compilation_error = ex
            result = str(ex)
        (root / ".openroad/pull-pending.json").unlink(missing_ok=True)
        (operation / "resolved").write_text("Disk-authoritative push completed\n")
    except Exception:
        if not marker.exists():
            mark_recovery(root, operation)
        raise
    message = f"{result}\nDisplaced source and tracking: {operation}"
    if compilation_error is not None:
        raise PostPushCompilationError(message) from compilation_error
    return message

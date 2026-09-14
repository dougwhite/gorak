"""Read-only three-way source comparison shared by synchronization commands."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import Literal

from lxml import etree

from .connection import OpenRoadConnection
from .export import backup_application_xml, read_applications
from .importer import signature
from .portable_source import read_document, restore_application, restore_component
from .project import ProjectError

Action = Literal["unchanged", "converged", "pull", "push", "conflict"]


@dataclass(frozen=True)
class Change:
    key: str
    action: Action
    disk: str
    database: str
    reason: str = ""


def change_kind(baseline: object, current: object) -> str:
    if baseline == current:
        return "unchanged"
    if baseline is None:
        return "added"
    if current is None:
        return "deleted"
    return "modified"


def compare(key: str, baseline: object, disk: object, database: object) -> Change:
    """Missing objects are None; timestamps are deliberately not conflict policy."""
    local_change = change_kind(baseline, disk)
    remote_change = change_kind(baseline, database)
    if disk == database:
        action: Action = "unchanged" if disk == baseline else "converged"
    elif disk == baseline:
        action = "pull"
    elif database == baseline:
        action = "push"
    else:
        action = "conflict"
    return Change(key, action, local_change, remote_change)


def xml_inventory(root: etree._Element, app: str) -> dict[str, object]:
    result: dict[str, object] = {}
    application = root.find("APPLICATION")
    if application is not None:
        result[app.casefold()] = signature(application)
    for node in root.findall("COMPONENT"):
        name = node.get("name")
        if not name:
            raise ProjectError("Component XML is missing its name")
        key = f"{app}/{name}".casefold()
        if key in result:
            raise ProjectError(f"Case-insensitive component collision: {key}")
        result[key] = signature(node)
    return result


def baseline_inventory(root: Path) -> tuple[dict[str, object], set[str]]:
    """Read caches in age order so a newer component export supersedes an app export."""
    result: dict[str, object] = {}
    tracking = root / ".openroad/tracked-applications.json"
    names = json.loads(tracking.read_text()) if tracking.exists() else []
    if not isinstance(names, list) or any(
        not isinstance(name, str) or not name or "/" in name or "\\" in name
        for name in names
    ):
        raise ProjectError("Invalid tracked application inventory")
    apps: set[str] = set(names)
    cache = root / ".openroad"
    for directory in cache.iterdir() if cache.exists() else []:
        if not directory.is_dir() or directory.name in {
            "pulls",
            "pushes",
            "imports",
            "runs",
        }:
            continue
        files = sorted(directory.glob("*.xml"), key=lambda p: p.stat().st_mtime_ns)
        if not files:
            continue
        apps.add(directory.name)
        for path in files:
            inventory = xml_inventory(read_document(path), directory.name)
            if directory.name.casefold() in inventory:
                # A full app export also records absence of deleted components.
                prefix = directory.name.casefold() + "/"
                result = {
                    key: value
                    for key, value in result.items()
                    if not key.startswith(prefix)
                }
            result.update(inventory)
    return result, apps


def plan_project(
    connection: OpenRoadConnection,
    root: Path,
    *,
    capture_dir: Path | None = None,
    reuse_xml: dict[str, Path] | None = None,
    database_hashes: dict[str, str] | None = None,
    inventory_sink: dict[str, str] | None = None,
) -> list[Change]:
    """Inspect disk and fresh XML without writing project state or database source."""
    if capture_dir is not None:
        capture_dir.mkdir(parents=True, exist_ok=False)
    baseline, apps = baseline_inventory(root)
    disk: dict[str, object] = {}
    invalid: dict[str, str] = {}
    seen: set[str] = set()
    for manifest in sorted(root.glob("*/app.json")):
        folder = manifest.parent
        if folder.name.startswith("."):
            continue
        app = folder.name
        if app.casefold() in seen:
            raise ProjectError(f"Case-insensitive application collision: {app}")
        seen.add(app.casefold())
        apps.add(app)
        try:
            disk[app.casefold()] = signature(restore_application(folder))
        except (ProjectError, ValueError, OSError, etree.XMLSyntaxError) as ex:
            invalid[app.casefold()] = str(ex)
        for source in sorted(folder.glob("*.w4gl")):
            key = f"{app}/{source.stem}".casefold()
            if key in disk or key in invalid:
                raise ProjectError(f"Case-insensitive component collision: {key}")
            try:
                disk[key] = signature(restore_component(source))
            except (ProjectError, ValueError, OSError, etree.XMLSyntaxError) as ex:
                invalid[key] = str(ex)
    if database_hashes is not None:
        baseline = dict(semantic_hashes(baseline))
        disk = dict(semantic_hashes(disk))
        database: dict[str, object] = dict(database_hashes)
    else:
        available = {
            app.name.casefold(): app.name for app in read_applications(connection)
        }
        database = {}
        with TemporaryDirectory(prefix="gorak-status-") as temporary:
            names = sorted({app.casefold() for app in apps} & available.keys())

            def export_one(item: tuple[int, str]) -> dict[str, object]:
                index, name = item
                path = Path(temporary) / f"{index}.xml"
                if reuse_xml is not None and name in reuse_xml:
                    copyfile(reuse_xml[name], path)
                else:
                    backup_application_xml(connection, available[name], path)
                inventory = xml_inventory(read_document(path), name)
                if capture_dir is not None:
                    copyfile(path, capture_dir / f"{index}.xml")
                return inventory

            # Independent applications have separate export paths. Consume in sorted
            # order and wait for every worker before cleaning the temporary directory.
            with ThreadPoolExecutor(max_workers=4) as executor:
                for inventory in executor.map(export_one, enumerate(names)):
                    database.update(inventory)
            if capture_dir is not None:
                (capture_dir / "applications.json").write_text(
                    json.dumps(
                        {name: f"{index}.xml" for index, name in enumerate(names)},
                        indent=2,
                    ),
                    encoding="utf-8",
                )
        if inventory_sink is not None:
            inventory_sink.update(semantic_hashes(database))
    changes = [
        compare(key, baseline.get(key), disk.get(key), database.get(key))
        for key in sorted(
            baseline.keys() | disk.keys() | database.keys() | invalid.keys()
        )
    ]
    for index, item in enumerate(changes):
        if item.key in invalid:
            changes[index] = Change(
                item.key, "conflict", "invalid", item.database, invalid[item.key]
            )
    # Removing an application conflicts with edits anywhere inside it on the other side.
    for index, item in enumerate(changes):
        if "/" in item.key:
            continue
        children = [c for c in changes if c.key.startswith(item.key + "/")]
        if (
            item.disk == "deleted"
            and any(c.database in {"added", "modified"} for c in children)
        ) or (
            item.database == "deleted"
            and any(c.disk in {"added", "modified", "invalid"} for c in children)
        ):
            changes[index] = Change(
                item.key,
                "conflict",
                item.disk,
                item.database,
                "Application deletion conflicts with component edits",
            )
    return changes


def format_plan(changes: list[Change]) -> list[dict[str, str]]:
    return [asdict(change) for change in changes if change.action != "unchanged"]


def semantic_hashes(inventory: dict[str, object]) -> dict[str, str]:
    """Compact exact semantic signatures without retaining XML/source in checkpoints."""
    return {
        key: hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                default=xml_special_signature,
            ).encode("ascii")
        ).hexdigest()
        for key, value in inventory.items()
    }


def xml_special_signature(value: object) -> dict[str, str]:
    """Preserve special XML node kinds in JSON semantic signatures."""
    for node, name in (
        (etree.Comment, "comment"),
        (etree.ProcessingInstruction, "processing_instruction"),
        (etree.Entity, "entity"),
    ):
        if value is node:
            return {"xml_node_kind": name}
    raise TypeError("Unsupported XML signature value")

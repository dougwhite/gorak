"""Read-only three-way source comparison shared by synchronization commands."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from shutil import copyfile
from typing import Literal

from lxml import etree

from . import comparison_cache
from .connection import OpenRoadConnection
from .export import backup_application_xml, read_applications
from .export_pipeline import prefetched_exports
from .native_normalization import signature as native_signature
from .native_styles import resolution_scope, validation_scope
from .operation_progress import report
from .portable_source import (
    cached_source_scope,
    comparison_application,
    comparison_component,
    read_document,
)
from .project import ProjectError


class SemanticDigest(str):
    """An already hashed normalized signature, distinct from raw source strings."""


def signature(node: etree._Element) -> SemanticDigest:
    # Release the expanded XML signature after each component instead of retaining
    # its nested Python containers for the entire project's three inventories.
    return SemanticDigest(semantic_hash(native_signature(node, pixel_geometry=True)))


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


def xml_inventory(
    root: etree._Element,
    app: str,
    *,
    raw_sink: dict[str, str] | None = None,
    memo: dict[str, str] | None = None,
    next_memo: dict[str, str] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {}

    def compare_node(node: etree._Element, key: str) -> SemanticDigest:
        raw = hashlib.sha256(
            etree.tostring(node, encoding="utf-8", with_tail=False)
        ).hexdigest()
        if raw_sink is not None:
            raw_sink[key] = raw
        cached = memo.get(raw) if memo is not None else None
        value = SemanticDigest(cached) if cached is not None else signature(node)
        if next_memo is not None:
            next_memo[raw] = value
        return value

    application = root.find("APPLICATION")
    if application is not None:
        result[app.casefold()] = compare_node(application, app.casefold())
    nodes = root.findall("COMPONENT")
    report(f"Comparing XML components: {app}", 0, len(nodes))
    for index, node in enumerate(nodes, 1):
        name = node.get("name")
        if not name:
            raise ProjectError("Component XML is missing its name")
        key = f"{app}/{name}".casefold()
        if key in result:
            raise ProjectError(f"Case-insensitive component collision: {key}")
        result[key] = compare_node(node, key)
        report(f"Comparing XML components: {app}", index, len(nodes))
    return result


def path_inventory(
    path: Path, app: str, scope: str, *, raw_sink: dict[str, str] | None = None
) -> dict[str, object]:
    """Reuse normalization only for byte-identical XML under this implementation."""
    key = comparison_cache.file_digest(path)
    cache_scope = "xml:" + scope + ":" + app
    saved = comparison_cache.load(cache_scope, key)
    cached = (
        comparison_cache.digests(saved.get("inventory")) if saved is not None else None
    )
    raw_cached = (
        comparison_cache.digests(saved.get("raw")) if saved is not None else None
    )
    if cached is not None and (raw_sink is None or raw_cached is not None):
        if raw_sink is not None and raw_cached is not None:
            raw_sink.update(raw_cached)
        report(f"Reusing byte-identical XML comparison: {app}")
        return {key: SemanticDigest(value) for key, value in cached.items()}
    memo_scope = "native-components:" + scope + ":" + app.casefold()
    previous = comparison_cache.load(memo_scope, "latest")
    memo = (
        comparison_cache.digests(previous.get("entries"))
        if previous is not None
        else None
    )
    raw: dict[str, str] = {}
    next_memo: dict[str, str] = {}
    inventory = xml_inventory(
        read_document(path), app, raw_sink=raw, memo=memo, next_memo=next_memo
    )
    if raw_sink is not None:
        raw_sink.update(raw)
    # External edits during a read must never publish under an earlier digest.
    if comparison_cache.file_digest(path) == key:
        comparison_cache.save(cache_scope, key, {"inventory": inventory, "raw": raw})
        comparison_cache.save(memo_scope, "latest", {"entries": next_memo})
    return inventory


def baseline_inventory(
    root: Path, *, raw_sink: dict[str, str] | None = None
) -> tuple[dict[str, object], set[str]]:
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
    directories = [
        directory
        for directory in (cache.iterdir() if cache.exists() else [])
        if directory.is_dir()
        and directory.name not in {"pulls", "pushes", "imports", "runs"}
    ]
    report("Reading baseline applications", 0, len(directories))
    for directory_index, directory in enumerate(directories, 1):
        report("Reading baseline applications", directory_index - 1, len(directories))
        files = sorted(directory.glob("*.xml"), key=lambda p: p.stat().st_mtime_ns)
        if not files:
            continue
        apps.add(directory.name)
        for path in files:
            report(f"Reading baseline XML: {directory.name}")
            raw: dict[str, str] = {}
            inventory = path_inventory(
                path, directory.name, str(root.resolve()), raw_sink=raw
            )

            if directory.name.casefold() in inventory:
                # A full app export also records absence of deleted components.
                prefix = directory.name.casefold() + "/"
                if raw_sink is not None:
                    for key in list(raw_sink):
                        if key.startswith(prefix):
                            del raw_sink[key]
                result = {
                    key: value
                    for key, value in result.items()
                    if not key.startswith(prefix)
                }
            result.update(inventory)
            if raw_sink is not None:
                raw_sink.update(raw)
    report("Reading baseline applications", len(directories), len(directories))
    return result, apps


def compare_source(
    root: Path,
    folder: Path,
    source: Path,
    records: dict[str, object],
    next_records: dict[str, object],
    *,
    application: bool = False,
    baseline_raw: str | None = None,
) -> SemanticDigest:
    inputs = [source]
    if not application:
        inputs.extend(
            companion
            for suffix in (
                ".wml",
                ".fielddefaults.json",
                ".queries.json",
                ".icons.json",
            )
            if (companion := source.with_suffix(suffix)).exists()
        )
    try:
        input_key = hashlib.sha256(
            (
                comparison_cache.content_key(inputs, root) + (baseline_raw or "absent")
            ).encode()
        ).hexdigest()
    except OSError:
        input_key = None
    record = comparison_cache.digests(records.get(source.name))
    if (
        record is not None
        and record.get("input") == input_key
        and "signature" in record
    ):
        result = SemanticDigest(record["signature"])
    else:
        result = signature(
            comparison_application(folder)
            if application
            else comparison_component(source)
        )
    if input_key is not None:
        next_records[source.name] = {"input": input_key, "signature": result}
    return result


@validation_scope()
@resolution_scope()
def local_inventory(
    root: Path,
) -> tuple[dict[str, object], set[str], dict[str, object], dict[str, str]]:
    scope = "local:" + str(root.resolve())
    report("Hashing local source and baseline bytes")
    try:
        cache_key = comparison_cache.project_key(root)
    except OSError:
        cache_key = None
    saved = comparison_cache.load(scope, cache_key) if cache_key is not None else None
    if saved is not None:
        baseline_cached = comparison_cache.digests(saved.get("baseline"))
        disk_cached = comparison_cache.digests(saved.get("disk"))
        apps_cached = saved.get("apps")
        if (
            baseline_cached is not None
            and disk_cached is not None
            and isinstance(apps_cached, list)
            and all(isinstance(app, str) for app in apps_cached)
        ):
            report("Reusing verified local comparison", 1, 1)
            return (
                {key: SemanticDigest(value) for key, value in baseline_cached.items()},
                set(apps_cached),
                {key: SemanticDigest(value) for key, value in disk_cached.items()},
                {},
            )
    raw_baseline: dict[str, str] = {}
    baseline, apps = baseline_inventory(root, raw_sink=raw_baseline)
    disk: dict[str, object] = {}
    invalid: dict[str, str] = {}
    seen: set[str] = set()
    manifests = sorted(
        p for p in root.glob("*/app.json") if not p.parent.name.startswith(".")
    )
    source_count = sum(1 + len(list(p.parent.glob("*.w4gl"))) for p in manifests)
    component_caches: list[tuple[str, str, dict[str, object]]] = []
    source_done = 0
    report("Comparing local source", source_done, source_count)
    for manifest in manifests:
        folder = manifest.parent
        if folder.name.startswith("."):
            continue
        app = folder.name
        if app.casefold() in seen:
            raise ProjectError(f"Case-insensitive application collision: {app}")
        seen.add(app.casefold())
        apps.add(app)
        memo_scope = "components:" + str(folder.resolve())
        try:
            dependency_key = (
                comparison_cache.shared_key(root, folder)
                if cache_key is not None
                else None
            )
        except OSError:
            dependency_key = None
        memo = (
            comparison_cache.load(memo_scope, dependency_key)
            if dependency_key is not None
            else None
        )
        records = memo if memo is not None else {}
        next_records: dict[str, object] = {}

        try:
            disk[app.casefold()] = compare_source(
                root,
                folder,
                manifest,
                records,
                next_records,
                application=True,
                baseline_raw=raw_baseline.get(app.casefold()),
            )
        except (ProjectError, ValueError, OSError, etree.XMLSyntaxError) as ex:
            invalid[app.casefold()] = str(ex)
        source_done += 1
        report("Comparing local source", source_done, source_count)
        for source in sorted(folder.glob("*.w4gl")):
            key = f"{app}/{source.stem}".casefold()
            if key in disk or key in invalid:
                raise ProjectError(f"Case-insensitive component collision: {key}")
            try:
                disk[key] = compare_source(
                    root,
                    folder,
                    source,
                    records,
                    next_records,
                    baseline_raw=raw_baseline.get(key),
                )
            except (ProjectError, ValueError, OSError, etree.XMLSyntaxError) as ex:
                invalid[key] = str(ex)
            source_done += 1
            report("Comparing local source", source_done, source_count)
        if dependency_key is not None:
            component_caches.append((memo_scope, dependency_key, next_records))
    if cache_key is not None:
        try:
            if comparison_cache.project_key(root) == cache_key:
                for memo_scope, dependency_key, records in component_caches:
                    comparison_cache.save(memo_scope, dependency_key, records)
                if not invalid:
                    comparison_cache.save(
                        scope,
                        cache_key,
                        {"baseline": baseline, "disk": disk, "apps": sorted(apps)},
                    )
        except OSError:
            pass
    return baseline, apps, disk, invalid


@cached_source_scope()
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
    baseline, apps, disk, invalid = local_inventory(root)
    if database_hashes is not None:
        baseline = dict(semantic_hashes(baseline))
        disk = dict(semantic_hashes(disk))
        database: dict[str, object] = dict(database_hashes)
    else:
        report("Listing database applications")
        available = {
            app.name.casefold(): app.name for app in read_applications(connection)
        }
        database = {}
        names = sorted({app.casefold() for app in apps} & available.keys())

        def export_one(name: str, path: Path) -> None:
            if reuse_xml is not None and name in reuse_xml:
                copyfile(reuse_xml[name], path)
            else:
                backup_application_xml(connection, available[name], path)

        report("Exporting and comparing database applications", 0, len(names))
        with prefetched_exports(
            names, connection.export_workers, export_one
        ) as pending:
            for index, (name, path) in enumerate(pending):
                report(f"Comparing database XML: {name}")
                database.update(path_inventory(path, name, str(root.resolve())))
                report(
                    "Exporting and comparing database applications",
                    index + 1,
                    len(names),
                )
                if capture_dir is not None:
                    copyfile(path, capture_dir / f"{index}.xml")
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
    report("Building change plan")
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
    return {key: semantic_hash(value) for key, value in inventory.items()}


def semantic_hash(value: object) -> str:
    if isinstance(value, SemanticDigest):
        return str(value)
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=xml_special_signature,
        ).encode("ascii")
    ).hexdigest()


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

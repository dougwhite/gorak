"""Read-only three-way source comparison shared by synchronization commands."""

import hashlib
import json
from collections.abc import Mapping
from contextlib import closing
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
    cached_node_at,
    cached_source_scope,
    comparison_application,
    comparison_component,
    read_document,
)
from .project import ProjectError
from .source_xml import application_children


class SemanticDigest(str):
    """An already hashed normalized signature, distinct from raw source strings."""


def raw_hash(node: etree._Element) -> str:
    return hashlib.sha256(
        etree.tostring(node, encoding="utf-8", with_tail=False)
    ).hexdigest()


@dataclass(eq=False)
class DeferredDigest:
    """Compare native bytes first; normalize only a component that differs."""

    raw: str
    path: Path
    tag: str
    name: str
    digest: str | None = None

    def resolve(self) -> str:
        if self.digest is None:
            try:
                node = cached_node_at(self.path, self.tag, self.name)
            except OSError as ex:
                raise ProjectError("Baseline changed during comparison; retry") from ex
            if node is None or raw_hash(node) != self.raw:
                raise ProjectError("Baseline changed during comparison; retry")
            self.digest = semantic_hash(native_signature(node, pixel_geometry=True))
        return self.digest

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DeferredDigest):
            if self.raw == other.raw:
                return True
            return self.resolve() == other.resolve()
        if isinstance(other, SemanticDigest):
            return self.resolve() == str(other)
        return False


def inventory_values(value: object) -> dict[str, object] | None:
    if isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, (SemanticDigest, DeferredDigest))
        for key, item in value.items()
    ):
        return value
    return None


def signature(node: etree._Element) -> object:
    # Exact bytes prove equality before applying the more expensive equivalences.
    raw = raw_hash(node)
    cached = comparison_cache.semantic(raw)
    if isinstance(cached, (SemanticDigest, DeferredDigest)):
        return cached
    digest = SemanticDigest(semantic_hash(native_signature(node, pixel_geometry=True)))
    comparison_cache.remember_semantic(raw, digest)
    return digest


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
    memo: dict[str, object] | None = None,
    next_memo: dict[str, object] | None = None,
    defer_path: Path | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {}

    def compare_node(node: etree._Element, key: str) -> object:
        raw = raw_hash(node)
        if raw_sink is not None:
            raw_sink[key] = raw
        cached = memo.get(raw) if memo is not None else None
        if isinstance(cached, (SemanticDigest, DeferredDigest)):
            value: object = cached
            if isinstance(cached, DeferredDigest) and defer_path is not None:
                value = DeferredDigest(
                    raw, defer_path, cached.tag, cached.name, cached.digest
                )
        elif defer_path is not None and not (
            any(len(flow) or flow.attrib for flow in node.findall("frmflow"))
            or node.xpath(".//processing-instruction() | .//script[*]")
        ):
            value = DeferredDigest(raw, defer_path, str(node.tag), node.get("name", ""))
        else:
            value = signature(node)
        comparison_cache.remember_semantic(
            raw, value, baseline_read=defer_path is not None
        )
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
    path: Path,
    app: str,
    scope: str,
    *,
    raw_sink: dict[str, str] | None = None,
    defer_path: Path | None = None,
    expected_digest: str | None = None,
) -> dict[str, object]:
    """Reuse normalization only for byte-identical XML under this implementation."""
    key = comparison_cache.file_digest(path)
    if expected_digest is not None and key != expected_digest:
        raise ProjectError("Native XML changed during comparison; retry")
    cache_scope = "xml:" + scope + ":" + app
    saved = comparison_cache.load(cache_scope, key)
    cached = inventory_values(saved.get("inventory")) if saved is not None else None
    raw_cached = (
        comparison_cache.digests(saved.get("raw")) if saved is not None else None
    )
    if cached is not None and (raw_sink is None or raw_cached is not None):
        if defer_path is not None:
            cached = {
                name: DeferredDigest(
                    value.raw, defer_path, value.tag, value.name, value.digest
                )
                if isinstance(value, DeferredDigest)
                else value
                for name, value in cached.items()
            }
        if raw_cached is not None:
            for name, raw_digest in raw_cached.items():
                if name in cached:
                    comparison_cache.remember_semantic(
                        raw_digest,
                        cached[name],
                        baseline_read=defer_path is not None,
                    )
        if raw_sink is not None and raw_cached is not None:
            raw_sink.update(raw_cached)
        report(f"Reusing byte-identical XML comparison: {app}")
        return cached
    memo_scope = "native-components:" + scope + ":" + app.casefold()
    previous = comparison_cache.load(memo_scope, "latest")
    memo = inventory_values(previous.get("entries")) if previous is not None else None
    raw: dict[str, str] = {}
    next_memo: dict[str, object] = {}
    inventory = xml_inventory(
        read_document(path),
        app,
        raw_sink=raw,
        memo=memo,
        next_memo=next_memo,
        defer_path=defer_path,
    )
    if raw_sink is not None:
        raw_sink.update(raw)
    # A caller may use the inventory to certify source equality. A changed
    # native read must not escape merely because its own cache was skipped.
    if comparison_cache.file_digest(path) != key:
        raise ProjectError("Native XML changed during comparison; retry")
    comparison_cache.save(cache_scope, key, {"inventory": inventory, "raw": raw})
    comparison_cache.save(memo_scope, "latest", {"entries": next_memo})
    return inventory


def baseline_inventory(
    root: Path,
    *,
    raw_sink: dict[str, str] | None = None,
    expected_digests: Mapping[str, str] | None = None,
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
            expected_digest = None
            if expected_digests is not None:
                expected_digest = expected_digests.get(
                    path.relative_to(root).as_posix()
                )
                if expected_digest is None:
                    raise ProjectError("Native XML changed during comparison; retry")
            raw: dict[str, str] = {}
            inventory = path_inventory(
                path,
                directory.name,
                str(root.resolve()),
                raw_sink=raw,
                defer_path=path if comparison_cache.active() else None,
                expected_digest=expected_digest,
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


def source_input_key(
    root: Path,
    source: Path,
    *,
    application: bool = False,
    baseline_raw: str | None = None,
    verified_digests: Mapping[str, str] | None = None,
) -> str:
    inputs = [source]
    if not application:
        for suffix in (
            ".wml",
            ".fielddefaults.json",
            ".queries.json",
            ".icons.json",
        ):
            companion = source.with_suffix(suffix)
            exists = (
                companion.relative_to(root).as_posix() in verified_digests
                if verified_digests is not None
                else companion.exists()
            )
            if exists:
                inputs.append(companion)
    return hashlib.sha256(
        (
            comparison_cache.content_key(
                inputs, root, verified_digests=verified_digests
            )
            + (baseline_raw or "absent")
        ).encode()
    ).hexdigest()


def compare_source(
    root: Path,
    folder: Path,
    source: Path,
    records: dict[str, object],
    next_records: dict[str, object],
    *,
    application: bool = False,
    baseline_raw: str | None = None,
    verified_digests: dict[str, str] | None = None,
) -> object:
    input_key: str | None
    try:
        input_key = source_input_key(
            root, source, application=application, baseline_raw=baseline_raw
        )
        if verified_digests is not None and input_key != source_input_key(
            root,
            source,
            application=application,
            baseline_raw=baseline_raw,
            verified_digests=verified_digests,
        ):
            # A transient edit must not attach the snapshot's comparison to
            # a cache key describing different source bytes.
            input_key = None
    except OSError:
        input_key = None
    record = records.get(source.name)
    result: object = None
    if (
        isinstance(record, dict)
        and record.get("input") == input_key
        and isinstance(record.get("signature"), (SemanticDigest, DeferredDigest))
    ):
        result = record["signature"]
        if isinstance(result, DeferredDigest):
            # The same native component may now live in a newer full-app XML
            # instead of its old component file. Baseline inventory has seeded
            # the current locator; never retain an obsolete memo's file path.
            current = comparison_cache.semantic(result.raw)
            result = (
                current
                if isinstance(current, (SemanticDigest, DeferredDigest))
                else None
            )
    if result is None:
        result = signature(
            comparison_application(folder)
            if application
            else comparison_component(source)
        )
    if input_key is not None:
        next_records[source.name] = {"input": input_key, "signature": result}
    return result


@comparison_cache.project_cached
@comparison_cache.scope()
@cached_source_scope()
@validation_scope()
@resolution_scope()
def local_inventory(
    root: Path,
) -> tuple[dict[str, object], set[str], dict[str, object], dict[str, str]]:
    scope = "local:" + str(root.resolve())
    report("Hashing local source and baseline bytes")
    source_digests: dict[str, str] = {}
    try:
        cache_key = comparison_cache.project_key(root, digest_sink=source_digests)
    except OSError:
        cache_key = None
    saved = comparison_cache.load(scope, cache_key) if cache_key is not None else None
    if saved is not None:
        baseline_cached = inventory_values(saved.get("baseline"))
        disk_cached = inventory_values(saved.get("disk"))
        apps_cached = saved.get("apps")
        if (
            baseline_cached is not None
            and disk_cached is not None
            and isinstance(apps_cached, list)
            and all(isinstance(app, str) for app in apps_cached)
        ):
            report("Reusing verified local comparison", 1, 1)
            return (
                baseline_cached,
                set(apps_cached),
                disk_cached,
                {},
            )
    raw_baseline: dict[str, str] = {}
    baseline, apps = baseline_inventory(
        root,
        raw_sink=raw_baseline,
        expected_digests=source_digests if cache_key is not None else None,
    )
    disk: dict[str, object] = {}
    invalid: dict[str, str] = {}
    seen: set[str] = set()
    manifests = sorted(
        p for p in root.glob("*/app.json") if not p.parent.name.startswith(".")
    )
    source_count = sum(1 + len(list(p.parent.glob("*.w4gl"))) for p in manifests)
    component_caches: list[tuple[str, str, dict[str, object]]] = []
    cache_valid = True
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
            if (
                dependency_key is not None
                and dependency_key
                != comparison_cache.shared_key(
                    root, folder, verified_digests=source_digests
                )
            ):
                dependency_key = None
        except OSError:
            dependency_key = None
        if dependency_key is None:
            cache_valid = False
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
                verified_digests=source_digests if cache_key is not None else None,
            )
        except (ProjectError, ValueError, OSError, etree.XMLSyntaxError) as ex:
            invalid[app.casefold()] = str(ex)
        source_done += 1
        report("Comparing local source", source_done, source_count)
        if manifest.name not in next_records:
            cache_valid = False
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
                    verified_digests=source_digests if cache_key is not None else None,
                )
            except (ProjectError, ValueError, OSError, etree.XMLSyntaxError) as ex:
                invalid[key] = str(ex)
            source_done += 1
            report("Comparing local source", source_done, source_count)
            if source.name not in next_records:
                cache_valid = False
        if dependency_key is not None:
            component_caches.append((memo_scope, dependency_key, next_records))
    if cache_key is not None:
        try:
            if comparison_cache.project_key(root) == cache_key:
                for memo_scope, dependency_key, records in component_caches:
                    comparison_cache.save(memo_scope, dependency_key, records)
                if not invalid and cache_valid:
                    comparison_cache.save(
                        scope,
                        cache_key,
                        {"baseline": baseline, "disk": disk, "apps": sorted(apps)},
                    )
        except OSError:
            pass
    return baseline, apps, disk, invalid


@comparison_cache.project_cached
@comparison_cache.scope()
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
    """Compare source with fresh XML, reusing verified comparison metadata."""
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
        local_folders = {
            manifest.parent.name.casefold(): manifest.parent
            for manifest in root.glob("*/app.json")
            if not manifest.parent.name.startswith(".")
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
                if (
                    name not in baseline
                    and name in disk
                    and name in database
                    and name not in invalid
                    and name in local_folders
                    and disk[name] != database[name]
                ):
                    # Fresh clones have no historical native representation.
                    # Apply the existing metadata overlay to current XML only
                    # for this comparison; the baseline remains absent.
                    try:
                        # All prefetched exports share a temporary directory;
                        # never retain their full trees in the baseline index.
                        with closing(application_children(path)) as native_children:
                            native_context = next(
                                (
                                    node
                                    for node in native_children
                                    if node.tag == "APPLICATION"
                                    and node.get("name", "").casefold() == name
                                ),
                                None,
                            )
                        if native_context is not None:
                            disk[name] = signature(
                                comparison_application(
                                    local_folders[name], native_context=native_context
                                )
                            )
                    except (ProjectError, ValueError, OSError, etree.XMLSyntaxError):
                        # Unsupported native details cannot prove equality;
                        # retain the original source comparison and conflict.
                        pass
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


@cached_source_scope()
def semantic_hashes(inventory: dict[str, object]) -> dict[str, str]:
    """Compact exact semantic signatures without retaining XML/source in checkpoints."""
    return {key: semantic_hash(value) for key, value in inventory.items()}


def semantic_hash(value: object) -> str:
    if isinstance(value, SemanticDigest):
        return str(value)
    if isinstance(value, DeferredDigest):
        return value.resolve()
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

"""Import readable component edits while preserving their complete source XML.

The database comparison is optimistic: OpenROAD does not expose an atomic
compare-and-import operation through backupapp. Do not edit the same component
in Workbench while an import is running.
"""

import re
from pathlib import Path
from uuid import uuid4

from lxml import etree

from .connection import OpenRoadConnection
from .errors import SourceVerificationError
from .export import backup_component_xml
from .import_backend import import_component_xml
from .project import ProjectError
from .project_lock import open_lock


def validate_name(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", value):
        raise ProjectError(f"Import requires an OpenROAD identifier: {value!r}")


def component_tree(path: Path, name: str) -> etree._Element:
    from .source_xml import read_tree

    tree = read_tree(path)
    nodes = [n for n in tree.getroot().findall("./COMPONENT") if n.get("name") == name]
    if len(nodes) != 1:
        raise ProjectError(f"Expected exactly one component named {name} in {path}")
    return nodes[0]


def signature(node: etree._Element) -> object:
    """Compare all XML content, ignoring only element-only formatting whitespace."""
    text = node.text or ""
    if node.tag == "obj_encoded":
        from .bitmap_codec import normalized

        text = normalized(text)
    mixed = any(isinstance(c, etree._ProcessingInstruction) for c in node)
    if len(node) and not mixed and not text.strip():
        text = ""
    return (
        (node.tag, node.target)
        if isinstance(node, etree._ProcessingInstruction)
        else node.tag,
        sorted(node.attrib.items()),
        text,
        [
            (signature(c), (c.tail or "") if mixed else (c.tail or "").strip())
            for c in node
        ],
    )


def import_component(
    connection: OpenRoadConnection,
    root: Path,
    app: str,
    component: str,
    dry_run: bool = False,
    *,
    advance_cache: bool = True,
) -> Path:
    """Validate, compare, import, and verify one component; retain recovery artifacts."""
    validate_name(app)
    validate_name(component)
    from .safe_pull import apply_files, fingerprint

    source_snapshot = fingerprint(root)
    cache = root / ".openroad" / app
    candidates = [
        p for p in [cache / f"{component}.xml", cache / f"{app}.xml"] if p.is_file()
    ]
    if not candidates:
        raise ProjectError("Import requires cached XML from a previous export")
    baseline_path = max(candidates, key=lambda p: p.stat().st_mtime_ns)
    source = root / app / f"{component}.w4gl"
    try:
        baseline = component_tree(baseline_path, component)
        source_bytes = source.read_bytes()
        markup = source.with_suffix(".wml")
        markup_bytes = markup.read_bytes() if markup.is_file() else None
        from .component_defaults import defaults_path

        defaults_files = {
            defaults_path(source): "source.fielddefaults.json",
            source.with_suffix(".queries.json"): "source.queries.json",
            root / "field_defaults.json": "root-field_defaults.json",
            source.parent / "field_defaults.json": "app-field_defaults.json",
        }
        from .image_assets import source_files

        defaults_files.update(
            {
                p: "assets/" + p.relative_to(source.parent).as_posix()
                for p in source_files(source.parent)
            }
        )
        defaults_files.update(
            {
                p: "root-assets/" + p.relative_to(root).as_posix()
                for p in source_files(root)
            }
        )
        defaults_bytes = {
            path: path.read_bytes() if path.is_file() else None
            for path in defaults_files
        }
    except (ValueError, OSError, etree.XMLSyntaxError) as ex:
        raise ProjectError(f"Cannot read import source: {ex}") from ex
    from copy import deepcopy

    from .portable_source import overlay_component

    try:
        overlay_component(deepcopy(baseline), source)
    except (ValueError, OSError, etree.XMLSyntaxError) as ex:
        raise ProjectError(f"Cannot validate import source {source}: {ex}") from ex

    operations = root / ".openroad" / "imports"
    operations.mkdir(parents=True, exist_ok=True)
    lock = operations / "import.lock"
    try:
        handle = open_lock(lock, "component import")
    except FileExistsError as ex:
        raise ProjectError(
            f"Another import may be active; inspect {lock} before removing it"
        ) from ex
    operation = operations / uuid4().hex
    try:
        with handle:
            operation.mkdir()
            (operation / "source.w4gl").write_bytes(source_bytes)
            if markup_bytes is not None:
                (operation / "source.wml").write_bytes(markup_bytes)
            for path, content in defaults_bytes.items():
                if content is not None:
                    retained = operation / defaults_files[path]
                    retained.parent.mkdir(parents=True, exist_ok=True)
                    retained.write_bytes(content)
            (operation / "baseline.xml").write_bytes(baseline_path.read_bytes())
            before = operation / "before.xml"
            backup_component_xml(connection, app, component, before)
            current = component_tree(before, component)
            if signature(current) != signature(baseline):
                raise ProjectError(
                    "Database component changed since export; reconcile it before importing"
                )
            overlay_component(current, source)
            submitted = operation / "submitted.xml"
            current.getroottree().write(
                str(submitted), encoding="UTF-8", xml_declaration=True
            )
            if dry_run:
                return operation
            if (
                source.read_bytes() != source_bytes
                or (markup.read_bytes() if markup.is_file() else None) != markup_bytes
                or any(
                    (p.read_bytes() if p.is_file() else None) != data
                    for p, data in defaults_bytes.items()
                )
            ):
                raise ProjectError("Local source changed while preparing import; retry")
            import_component_xml(
                connection, app, component, submitted, operation / "import.log"
            )
            after = operation / "after.xml"
            backup_component_xml(connection, app, component, after)
            from .frame_geometry import normalized_markup

            actual = component_tree(after, component)
            normalized = normalized_markup(current, actual)
            from .contract_source import equivalent

            matches = equivalent(actual, current)
            if not matches and normalized is None:
                raise SourceVerificationError(
                    "Post-import verification failed; database may have changed"
                )
            if (
                source.read_bytes() != source_bytes
                or (markup.read_bytes() if markup.is_file() else None) != markup_bytes
                or any(
                    (p.read_bytes() if p.is_file() else None) != data
                    for p, data in defaults_bytes.items()
                )
            ):
                raise ProjectError(
                    "Local source changed during import; baseline not advanced"
                )
            if normalized is not None:
                (operation / "normalized.wml").write_text(normalized)
            # Source canonicalization is staged with baselines by the push executor.
            if advance_cache:
                destination = cache / f"{component}.xml"
                replacement = cache / f".{component}-{uuid4().hex}.xml"
                replacement.write_bytes(after.read_bytes())
                if normalized is not None:
                    apply_files(
                        root,
                        {destination: after.read_bytes(), markup: normalized.encode()},
                        operation,
                        source_snapshot,
                    )
                    replacement.unlink()
                else:
                    replacement.replace(destination)
            (operation / "verified").write_text(
                "Import and XML verification succeeded\n"
            )
            return operation
    except Exception as ex:
        error_type = (
            SourceVerificationError
            if isinstance(ex, SourceVerificationError)
            else ProjectError
        )
        raise error_type(
            f"{ex}\nImport artifacts: {operation}. If import started, the database may "
            "have changed; inspect import.log and re-export before retrying."
        ) from ex
    finally:
        lock.unlink()

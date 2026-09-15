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
from .export import backup_component_xml
from .import_backend import import_component_xml
from .project import ProjectError


def validate_name(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", value):
        raise ProjectError(f"Import requires an OpenROAD identifier: {value!r}")


def component_tree(path: Path, name: str) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, strip_cdata=False)
    tree = etree.parse(str(path), parser)
    if tree.docinfo.doctype:
        raise ProjectError("Import does not support XML document type declarations")
    nodes = [n for n in tree.getroot().findall("./COMPONENT") if n.get("name") == name]
    if len(nodes) != 1:
        raise ProjectError(f"Expected exactly one component named {name} in {path}")
    return nodes[0]


def signature(node: etree._Element) -> object:
    """Compare all XML content, ignoring only element-only formatting whitespace."""
    text = node.text or ""
    if len(node) and not text.strip():
        text = ""
    return (
        node.tag,
        sorted(node.attrib.items()),
        text,
        [(signature(c), (c.tail or "").strip()) for c in node],
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
        handle = lock.open("x")
    except FileExistsError as ex:
        raise ProjectError(
            f"Another import may be active; inspect {lock} before removing it"
        ) from ex
    operation = operations / uuid4().hex
    try:
        with handle:
            operation.mkdir()
            handle.write(str(operation))
            handle.flush()
            (operation / "source.w4gl").write_bytes(source_bytes)
            if markup_bytes is not None:
                (operation / "source.wml").write_bytes(markup_bytes)
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
            ):
                raise ProjectError("Local source changed while preparing import; retry")
            import_component_xml(
                connection, app, component, submitted, operation / "import.log"
            )
            after = operation / "after.xml"
            backup_component_xml(connection, app, component, after)
            from .frame_geometry import normalized_markup

            actual = component_tree(after, component)
            from .readable_source import is_complete

            normalized = normalized_markup(
                current, actual, complete=is_complete(source)
            )
            from .contract_source import equivalent

            matches = (
                signature(actual) == signature(current)
                if is_complete(source)
                else equivalent(actual, current)
            )
            if not matches and normalized is None:
                raise ProjectError(
                    "Post-import verification failed; database may have changed"
                )
            if (
                source.read_bytes() != source_bytes
                or (markup.read_bytes() if markup.is_file() else None) != markup_bytes
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
        raise ProjectError(
            f"{ex}\nImport artifacts: {operation}. If import started, the database may "
            "have changed; inspect import.log and re-export before retrying."
        ) from ex
    finally:
        lock.unlink()

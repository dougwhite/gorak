"""Import existing procedure/class scripts while preserving their source XML.

The database comparison is optimistic: OpenROAD does not expose an atomic
compare-and-import operation through backupapp. Do not edit the same component
in Workbench while an import is running.
"""

import re
import tomllib
from pathlib import Path
from uuid import uuid4

from lxml import etree

from .connection import OpenRoadConnection
from .export import backup_component_xml
from .import_backend import import_component_xml
from .parser import encode_w4gl, parse_component_node, parse_w4gl, split_w4gl
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
) -> Path:
    """Validate, compare, import, and verify one script; retain recovery artifacts."""
    validate_name(app)
    validate_name(component)
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
        original = parse_component_node(baseline)
        source_bytes = source.read_bytes()
        edited = parse_w4gl(source_bytes.decode("utf-8"), component)
    except (ValueError, OSError, etree.XMLSyntaxError) as ex:
        raise ProjectError(f"Cannot read import source: {ex}") from ex
    if original.type not in {"proc4glsource", "classsource"}:
        raise ProjectError(
            "Import currently supports existing procedures and classes only"
        )
    if (
        original.type != edited.type
        or original.props != edited.props
        or tomllib.loads(split_w4gl(source_bytes.decode("utf-8"))[0])
        != tomllib.loads(split_w4gl(encode_w4gl(original))[0])
    ):
        raise ProjectError("Metadata edits are not supported; only change the script")
    if original.script is None or edited.script is None:
        raise ProjectError(
            "Import requires an existing script and a === script section"
        )

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
            (operation / "baseline.xml").write_bytes(baseline_path.read_bytes())
            before = operation / "before.xml"
            backup_component_xml(connection, app, component, before)
            current = component_tree(before, component)
            if signature(current) != signature(baseline):
                raise ProjectError(
                    "Database component changed since export; reconcile it before importing"
                )
            script = current.find("script")
            if script is None:
                raise ProjectError("Database component has no script")
            # Retain the export's leading/trailing script whitespace.
            previous = script.text or ""
            leading = previous[: len(previous) - len(previous.lstrip())]
            trailing = previous[len(previous.rstrip()) :]
            script.text = etree.CDATA(leading + edited.script + trailing)
            submitted = operation / "submitted.xml"
            current.getroottree().write(
                str(submitted), encoding="UTF-8", xml_declaration=True
            )
            if dry_run:
                return operation
            if source.read_bytes() != source_bytes:
                raise ProjectError("Local source changed while preparing import; retry")
            import_component_xml(
                connection, app, component, submitted, operation / "import.log"
            )
            after = operation / "after.xml"
            backup_component_xml(connection, app, component, after)
            if signature(component_tree(after, component)) != signature(current):
                raise ProjectError(
                    "Post-import verification failed; database may have changed"
                )
            # Do not advance other components' sync metadata or rewrite edited source.
            destination = cache / f"{component}.xml"
            replacement = cache / f".{component}-{uuid4().hex}.xml"
            replacement.write_bytes(after.read_bytes())
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

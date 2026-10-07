"""Current readable reconstruction and native baselines for verified comparisons."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path

from lxml import etree

from .project import ProjectError


def read_document(path: Path) -> etree._Element:
    from .source_xml import read_tree

    return read_tree(path).getroot()


class CachedSourceIndex:
    """Index parsed native cache files for a read-only comparison operation."""

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.files: dict[
            Path,
            tuple[
                tuple[int, int, int], dict[tuple[str, str], list[etree._Element]], bool
            ],
        ] = {}

    def lookup(self, folder: Path, tag: str, name: str) -> etree._Element | None:
        if folder != self.folder:
            self.files.clear()  # Bound retained XML to one application.
            self.folder = folder
        cache = folder.parent / ".openroad" / folder.name
        paths = sorted(
            cache.glob("*.xml"), key=lambda p: p.stat().st_mtime_ns, reverse=True
        )
        for path in paths:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
            entry = self.files.get(path)
            if entry is None or entry[0] != stamp:
                root = read_document(path)
                nodes: dict[tuple[str, str], list[etree._Element]] = {}
                for node in root:
                    if isinstance(node.tag, str):
                        nodes.setdefault(
                            (node.tag, node.get("name", "").casefold()), []
                        ).append(node)
                entry = (stamp, nodes, root.find("APPLICATION") is not None)
                self.files[path] = entry
            matches = entry[1].get((tag, name.casefold()), [])
            if len(matches) > 1:
                raise ProjectError(f"Ambiguous cached source: {path}")
            if matches:
                # Callers overlay metadata; the shared index must remain pristine.
                return deepcopy(matches[0])
            if tag == "COMPONENT" and entry[2]:
                return None
        return None


_source_index: ContextVar[CachedSourceIndex | None] = ContextVar(
    "source_index", default=None
)


@contextmanager
def cached_source_scope() -> Iterator[None]:
    if _source_index.get() is not None:
        yield
        return
    token = _source_index.set(CachedSourceIndex())
    try:
        yield
    finally:
        _source_index.reset(token)


def cached_node(folder: Path, tag: str, name: str) -> etree._Element | None:
    """Read an older checkout baseline, respecting newer full-export absence."""
    return (_source_index.get() or CachedSourceIndex()).lookup(folder, tag, name)


def overlay_component(node: etree._Element, path: Path) -> etree._Element:
    """Reconstruct edited source; preserve native serialization on a verified no-op."""
    from .component_edits import overlay_metadata
    from .contract_source import decode_component, equivalent
    from .parser import NS, WML_COMPONENT_TYPES

    if node.get(f"{{{NS['xsi']}}}type") not in WML_COMPONENT_TYPES:
        overlay_metadata(node, path)
        from .class_icons import overlay_icons

        overlay_icons(node, path)
        return node
    replacement = decode_component(path)
    from .query_metadata import overlay_queries

    # Enforce missing-sidecar protection against the authoritative baseline.
    overlay_queries(deepcopy(node), path)
    from .class_icons import overlay_icons

    overlay_icons(deepcopy(node), path)
    if equivalent(replacement, node):
        return node
    node.attrib.clear()
    node.attrib.update(replacement.attrib)
    node.text = replacement.text
    node[:] = list(replacement)
    return node


def restore_component(path: Path) -> etree._Element:
    """Reconstruct only from versioned readable files, never cached XML."""
    from .xml_writer import new_component

    return new_component(path)


def restore_application(folder: Path) -> etree._Element:
    """Reconstruct application metadata without cache or companion lookup."""
    from .xml_writer import new_application

    return new_application(folder)


def comparison_component(path: Path) -> etree._Element:
    """Preserve unrepresented baseline details for three-way comparison only."""
    baseline = cached_node(path.parent, "COMPONENT", path.stem)
    if baseline is not None:
        return overlay_component(deepcopy(baseline), path)
    return restore_component(path)


def comparison_application(folder: Path) -> etree._Element:
    from .parser import parse_application_xml
    from .xml_writer import document

    desired = restore_application(folder)
    baseline = cached_node(folder, "APPLICATION", folder.name)
    if baseline is None:
        return desired
    from .source_xml import from_bytes

    old = parse_application_xml(from_bytes(document([baseline])))
    new = parse_application_xml(from_bytes(document([desired])))
    if (
        old.application == new.application
        and old.included_applications == new.included_applications
    ):
        return baseline
    managed = {
        "versshortremarks",
        "included_apps",
        "procstart",
        "databasename",
        "database_type",
        "windowicon",
        "appflags",
    }
    for child in list(baseline):
        if child.tag in managed:
            baseline.remove(child)
    baseline.extend(desired)
    order = [
        "versshortremarks",
        "extension",
        "taggedvalues",
        "included_apps",
        "procstart",
        "databasename",
        "database_type",
        "commandline",
        "windowicon",
        "globalsfile",
        "appflags",
    ]
    baseline[:] = sorted(baseline, key=lambda child: order.index(str(child.tag)))
    return baseline

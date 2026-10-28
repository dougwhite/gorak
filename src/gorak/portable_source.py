"""Current readable reconstruction and native baselines for verified comparisons."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from xml.parsers import expat

from lxml import etree

from .project import ProjectError


def read_document(path: Path, *, data: bytes | None = None) -> etree._Element:
    from .source_xml import from_bytes, read_tree

    return read_tree(path).getroot() if data is None else from_bytes(data)


def _source_stamp(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    # Windows ctime may be creation time; stamps are only refresh hints.
    # Requested spans and scope completion independently verify actual bytes.
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size


@dataclass(frozen=True)
class _SourceSpan:
    start: int
    end: int
    digest: bytes


def _source_spans(data: bytes) -> list[_SourceSpan] | None:
    """Locate direct XML children with a parser, including CDATA and empty tags."""
    parser = expat.ParserCreate()
    encoding = "ascii"
    if data.startswith((b"\xff\xfe", b"<\x00")):
        encoding = "utf-16-le"
    elif data.startswith((b"\xfe\xff", b"\x00<")):
        encoding = "utf-16-be"
    end_tag, empty_tag = ">".encode(encoding), "/>".encode(encoding)
    quotes = {"'".encode(encoding), '"'.encode(encoding)}
    depth = 0
    start = 0
    empty = False
    result: list[_SourceSpan] = []

    def opened(name: str, attributes: dict[str, str]) -> None:
        nonlocal depth, start, empty
        depth += 1
        if depth == 2:
            start = parser.CurrentByteIndex
            # The parser establishes nesting. Inspect only this opening token
            # to distinguish <item/> from <item></item>, respecting attributes.
            quote = None
            for offset in range(start, len(data), len(end_tag)):
                character = data[offset : offset + len(end_tag)]
                if quote is not None:
                    if character == quote:
                        quote = None
                elif character in quotes:
                    quote = character
                elif character == end_tag:
                    empty = (
                        data[offset - len(end_tag) : offset + len(end_tag)] == empty_tag
                    )
                    break
            else:
                raise ValueError("Missing opening tag terminator")

    def closed(name: str) -> None:
        nonlocal depth
        if depth == 2:
            end = parser.CurrentByteIndex
            # Expat points after an empty element, but before a closing tag.
            if not empty:
                found = data.find(end_tag, end)
                if found < 0:
                    raise ValueError("Missing closing tag")
                end = found + len(end_tag)
            result.append(
                _SourceSpan(
                    start, end, hashlib.sha256(memoryview(data)[start:end]).digest()
                )
            )
        depth -= 1

    parser.StartElementHandler = opened
    parser.EndElementHandler = closed
    try:
        parser.Parse(data, True)
    except (expat.ExpatError, ValueError):
        # libxml2 accepts some encodings Expat does not. Keep the existing XML
        # acceptance contract, using whole-file verification for this rare case.
        return None
    return result


def _range_digest(path: Path, start: int = 0, end: int | None = None) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        stream.seek(start)
        remaining = None if end is None else end - start
        while remaining is None or remaining:
            chunk = stream.read(
                1024 * 1024 if remaining is None else min(remaining, 1024 * 1024)
            )
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
        if remaining:
            raise ProjectError("Baseline changed during comparison; retry")
    return digest.digest()


@dataclass
class _CachedFile:
    stamp: tuple[int, int, int]
    nodes: dict[tuple[str, str], list[etree._Element]]
    complete: bool
    digest: bytes
    spans: dict[etree._Element, _SourceSpan]
    strict: bool = False

    def verify(self, path: Path, node: etree._Element | None = None) -> None:
        span = self.spans.get(node) if node is not None else None
        actual = (
            _range_digest(path, span.start, span.end) if span else _range_digest(path)
        )
        if actual != (span.digest if span else self.digest):
            raise ProjectError("Baseline changed during comparison; retry")


class CachedSourceIndex:
    """Index one application's immutable XML, verifying the bytes being reused."""

    def __init__(self) -> None:
        self.folder: Path | None = None
        self.files: dict[Path, _CachedFile] = {}

    def verify(self) -> None:
        # Span checks do not prove surrounding document structure or absence.
        # Check every file once before discarding its index or returning results.
        for path, entry in self.files.items():
            entry.verify(path)

    def entry(self, path: Path) -> _CachedFile:
        if path.parent != self.folder:
            self.verify()
            self.files.clear()  # Bound retained XML to one application.
            self.folder = path.parent
        stamp = _source_stamp(path)
        entry = self.files.get(path)
        if entry is not None and entry.stamp != stamp and entry.strict:
            entry.verify(path)
            entry.stamp = stamp
        if entry is None or entry.stamp != stamp:
            from .comparison_cache import read_xml_bytes

            data = read_xml_bytes(path)
            # Both the parse and byte-span proofs describe exactly these bytes.
            root = read_document(path, data=data)
            nodes: dict[tuple[str, str], list[etree._Element]] = {}
            children = [node for node in root if isinstance(node.tag, str)]
            spans = _source_spans(data)
            for node in children:
                nodes.setdefault(
                    (str(node.tag), node.get("name", "").casefold()), []
                ).append(node)
            entry = _CachedFile(
                stamp,
                nodes,
                root.find("APPLICATION") is not None,
                hashlib.sha256(data).digest(),
                dict(zip(children, spans, strict=True)) if spans is not None else {},
            )
            self.files[path] = entry
        return entry

    def lookup_file(
        self, path: Path, tag: str, name: str, *, clone: bool = True
    ) -> etree._Element | None:
        entry = self.entry(path)
        entry.strict |= not clone
        matches = entry.nodes.get((tag, name.casefold()), [])
        if len(matches) > 1:
            raise ProjectError(f"Ambiguous cached source: {path}")
        node = matches[0] if matches else None
        entry.verify(path, node)
        # Callers overlay metadata; the shared index must remain pristine.
        return deepcopy(node) if clone and node is not None else node

    def lookup(
        self, folder: Path, tag: str, name: str, *, clone: bool = True
    ) -> etree._Element | None:
        cache = folder.parent / ".openroad" / folder.name
        paths = sorted(
            cache.glob("*.xml"),
            key=lambda p: (p.stat().st_mtime_ns, p.name),
            reverse=True,
        )
        for path in paths:
            node = self.lookup_file(path, tag, name, clone=clone)
            if node is not None:
                return node
            if tag == "COMPONENT" and self.entry(path).complete:
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
    index = CachedSourceIndex()
    token = _source_index.set(index)
    try:
        yield
        try:
            index.verify()
        except OSError as ex:
            raise ProjectError("Baseline changed during comparison; retry") from ex
    finally:
        _source_index.reset(token)


def cached_node(
    folder: Path, tag: str, name: str, *, clone: bool = True
) -> etree._Element | None:
    """Read an older checkout baseline, respecting newer full-export absence."""
    with cached_source_scope():
        index = _source_index.get()
        assert index is not None
        return index.lookup(folder, tag, name, clone=clone)


def cached_node_at(path: Path, tag: str, name: str) -> etree._Element | None:
    """Resolve an exact observed baseline, including superseded component files."""
    with cached_source_scope():
        index = _source_index.get()
        assert index is not None
        return index.lookup_file(path, tag, name, clone=False)


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
    from .comparison_inputs import bound, path_for_read, verify_baseline

    baseline = cached_node(path.parent, "COMPONENT", path.stem, clone=not bound())
    verify_baseline(baseline)
    path = path_for_read(path)
    if baseline is not None:
        return overlay_component(deepcopy(baseline) if bound() else baseline, path)
    return restore_component(path)


def comparison_application(
    folder: Path, *, native_context: etree._Element | None = None
) -> etree._Element:
    from .comparison_inputs import bound, path_for_read, verify_baseline
    from .parser import parse_application_xml
    from .xml_writer import document

    desired = restore_application(path_for_read(folder))
    baseline = cached_node(folder, "APPLICATION", folder.name, clone=not bound())
    verify_baseline(baseline)
    if baseline is not None and bound():
        baseline = deepcopy(baseline)
    if baseline is None and native_context is not None:
        baseline = deepcopy(native_context)
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

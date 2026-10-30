"""Native stylesheet inheritance by group name and fixed, numbered style slots."""

import hashlib
import json
import pickle
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, TypeGuard, cast
from urllib.parse import quote

from lxml import etree

from .errors import ProjectError
from .source_reads import exists as source_exists
from .source_reads import read_text as read_source_text
from .style_values import XSI, decode_value, encode_value, numbered
from .style_values import difference as property_difference
from .style_values import merge as merge_properties
from .xml_text import find_text

Json = dict[str, Any]


def group_key(name: str, occurrence: int) -> str:
    # Literal colon/percent characters must not collide with repeated-group labels.
    label = quote(name, safe=" _-.")
    return label if occurrence == 1 else f"{label}:{occurrence}"


def without_rows(node: etree._Element) -> etree._Element:
    result = deepcopy(node)
    rows = result.findall("row")
    if list(result)[: len(rows)] != rows:
        raise ProjectError(
            "Stylesheet arrays require native rows before container metadata"
        )
    for row in rows:
        result.remove(row)
    if not (result.text or "").strip():
        result.text = None
    return result


def is_absent(node: etree._Element | None) -> bool:
    """OpenROAD drops completely empty stylesheet containers during import."""
    return node is None or (
        not node.attrib and not len(node) and not (node.text or "").strip()
    )


def encode(node: etree._Element) -> Json:
    """Preserve group metadata and samples without suppressing native properties."""
    cache = _resolved.get()
    if cache is None or node.tag != "fielddefaults":
        return _encode_uncached(node)
    key = hashlib.sha256(
        etree.tostring(node, encoding="utf-8", with_tail=False)
    ).digest()
    cached = cache.get("encode", key)
    if isinstance(cached, bytes):
        return cast(Json, pickle.loads(cached))
    value = _encode_uncached(node)
    cache.put("encode", key, pickle.dumps(value, protocol=5))
    return value


def _encode_uncached(node: etree._Element) -> Json:
    if node.tag != "fielddefaults":
        raise ProjectError("Native stylesheet root must be fielddefaults")
    from .native_normalization import explicit_row_types

    node = deepcopy(node)
    explicit_row_types(node)
    groups: Json = {}
    counts: dict[str, int] = {}
    for row in node.findall("row"):
        name = find_text(row, "clienttext") or ""
        counts[name] = counts.get(name, 0) + 1
        key = group_key(name, counts[name])
        wrapper = deepcopy(row)
        children = row.find("childfields")
        styles: Json = {}
        if children is not None:
            wrapper.replace(wrapper.find("childfields"), without_rows(children))
            styles = {
                f"style{i}": encode_value(style)
                for i, style in enumerate(children.findall("row"), 1)
            }
        groups[key] = {
            "properties": encode_value(wrapper, object_value=True),
            "styles": styles,
        }
    return {
        "properties": encode_value(without_rows(node), object_value=True),
        "group_order": list(groups),
        "groups": groups,
    }


def decode(value: Json) -> etree._Element:
    cache = _resolved.get()
    if cache is None:
        return _decode_uncached(value)
    try:
        key = pickle.dumps(value, protocol=5)
    except (pickle.PickleError, TypeError, AttributeError):
        return _decode_uncached(value)
    cached = cache.get("decode", key)
    if isinstance(cached, etree._Element):
        return deepcopy(cached)
    result = _decode_uncached(value)
    # Keep an XML tree so character references and CDATA never pass through a
    # parser again. Budget both character buffers and native nodes conservatively.
    size = len(etree.tostring(result, encoding="utf-8", with_tail=False)) * 8
    size += sum(1 + len(node.attrib) for node in result.iter()) * 128
    if len(key) + len("decode") + size <= _COMPARISON_MAX_BYTES:
        cache.put("decode", key, deepcopy(result), size=size)
    return result


def _decode_uncached(value: Json) -> etree._Element:
    if not isinstance(value, dict) or set(value) != {
        "properties",
        "group_order",
        "groups",
    }:
        raise ProjectError(
            "Invalid native stylesheet: expected properties, group_order and groups"
        )
    order, groups = value["group_order"], value["groups"]
    if (
        not isinstance(groups, dict)
        or not isinstance(order, list)
        or any(not isinstance(k, str) for k in order)
        or len(order) != len(set(order))
        or set(order) != set(groups)
    ):
        raise ProjectError("Group order must name each native group exactly once")
    result = decode_value("fielddefaults", value["properties"])
    if result.findall("row"):
        raise ProjectError("Native groups belong in groups, not root properties")
    counts: dict[str, int] = {}
    for index, key in enumerate(order):
        group = groups[key]
        if not isinstance(group, dict) or set(group) != {"properties", "styles"}:
            raise ProjectError(f"Invalid native stylesheet group: {key}")
        row = decode_value("row", group["properties"])
        name = find_text(row, "clienttext") or ""
        counts[name] = counts.get(name, 0) + 1
        if group_key(name, counts[name]) != key:
            raise ProjectError(
                f"Group label does not match its native name/occurrence: {key}"
            )
        styles = group["styles"]
        slots = numbered(styles, "style")
        children = row.find("childfields")
        if children is not None and children.findall("row"):
            raise ProjectError(
                "Native style entries belong in styles, not group properties"
            )
        if slots and children is None:
            raise ProjectError(f"Missing native childfields container for {key}")
        for position, slot in enumerate(slots):
            field = decode_value("row", styles[slot])
            if not field.get(XSI):
                raise ProjectError(f"Native field type required for {key}/{slot}")
            assert children is not None
            children.insert(position, field)
        result.insert(index, row)
    return result


_validated: ContextVar[set[bytes] | None] = ContextVar("validated_styles", default=None)


@contextmanager
def validation_scope() -> Iterator[None]:
    """Reuse successful validation only within one operation, keyed by content."""
    if _validated.get() is not None:
        yield
        return
    token = _validated.set(set())
    try:
        yield
    finally:
        _validated.reset(token)


def _validation_key(stylesheet: Json) -> bytes:
    # JSON would conflate non-string mapping keys and tuple/list containers.
    # Never let malformed programmatic inputs share a valid sheet's cache key.
    def check(value: Any) -> None:
        if isinstance(value, dict):
            for name, child in value.items():
                if not isinstance(name, str):
                    raise TypeError("Stylesheet cache requires string keys")
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise TypeError("Stylesheet cache requires JSON containers")

    check(stylesheet)
    # Ignore Python object sharing while retaining meaningful property order.
    return hashlib.sha256(
        json.dumps(stylesheet, ensure_ascii=False, separators=(",", ":")).encode()
    ).digest()


def validate(stylesheet: Json) -> bytes | None:
    cache = _validated.get()
    key = None
    if cache is not None:
        try:
            key = _validation_key(stylesheet)
        except (TypeError, ValueError):
            pass  # The native validator supplies the authoritative diagnostic.
        if key in cache:
            return key
    decode(stylesheet)
    if cache is not None and key is not None:
        if len(cache) >= 8192:
            cache.clear()
        cache.add(key)
    return key


def complete(stylesheet: Json) -> Json:
    """A standalone root contains its complete named stylesheet, without a parent."""
    validate(stylesheet)
    return {"standalone": True, **deepcopy(stylesheet)}


def empty_delta() -> Json:
    """No properties supplied means inherit the parent unchanged."""
    return {}


def has_overrides(layer: Json) -> bool:
    return bool(layer)


def difference(parent: Json, desired: Json) -> Json:
    parent_key = validate(parent)
    desired_key = validate(desired)
    # Validation already computed an order-sensitive content identity. Equal
    # sheets need no second recursive walk to discover an empty difference.
    if parent_key is not None and parent_key == desired_key:
        return {}
    return property_difference(parent, desired)


def is_native_layer(value: Any) -> TypeGuard[Json]:
    """Recognise named stylesheet properties without a source version marker."""
    return isinstance(value, dict) and not set(value) - {
        "absent",
        "standalone",
        "properties",
        "group_order",
        "groups",
        "$order",
        "$before",
    }


_COMPARISON_MAX_ENTRIES = 32
_COMPARISON_MAX_BYTES = 32 * 1024 * 1024


class _ComparisonStyles:
    """Immutable results with one shared size budget for comparison operations."""

    def __init__(self) -> None:
        self.entries: dict[tuple[str, bytes], tuple[object, int]] = {}
        self.bytes = 0

    def get(self, kind: str, key: bytes) -> object:
        entry = self.entries.pop((kind, key), None)
        if entry is not None:
            self.entries[(kind, key)] = entry
            return entry[0]
        return None

    def put(
        self,
        kind: str,
        key: bytes,
        value: bytes | etree._Element,
        *,
        size: int | None = None,
    ) -> None:
        previous = self.entries.pop((kind, key), None)
        if previous is not None:
            self.bytes -= previous[1]
        if size is None:
            assert isinstance(value, bytes)
            size = len(value)
        size += len(kind) + len(key)
        if size > _COMPARISON_MAX_BYTES:
            return
        while self.entries and (
            len(self.entries) >= _COMPARISON_MAX_ENTRIES
            or self.bytes + size > _COMPARISON_MAX_BYTES
        ):
            oldest_kind, oldest_key = next(iter(self.entries))
            oldest = self.entries.pop((oldest_kind, oldest_key))
            self.bytes -= oldest[1]
        self.entries[(kind, key)] = (value, size)
        self.bytes += size


_resolved: ContextVar[_ComparisonStyles | None] = ContextVar(
    "resolved_styles", default=None
)


@contextmanager
def resolution_scope() -> Iterator[None]:
    """Reuse stylesheet conversion/resolution only inside one bounded comparison."""
    if _resolved.get() is not None:
        yield
        return
    token = _resolved.set(_ComparisonStyles())
    try:
        yield
    finally:
        _resolved.reset(token)


def resolve(parent: Json | None, layer: Json) -> Json:
    cache = _resolved.get()
    if cache is None:
        return _resolve_uncached(parent, layer)
    try:
        key = pickle.dumps((parent, layer), protocol=5)
    except (pickle.PickleError, TypeError, AttributeError):
        return _resolve_uncached(parent, layer)
    value = cache.get("resolve", key)
    if not isinstance(value, bytes):
        value = pickle.dumps(_resolve_uncached(parent, layer), protocol=5)
        cache.put("resolve", key, value)
    return cast(Json, pickle.loads(value))


def _resolve_uncached(parent: Json | None, layer: Json) -> Json:
    if not is_native_layer(layer):
        raise ProjectError(
            "Unsupported stylesheet properties; re-export the application"
        )
    if "absent" in layer:
        raise ProjectError("Only frame stylesheet sidecars can use absent: true")
    values = {key: value for key, value in layer.items() if key != "standalone"}
    if "standalone" in layer:
        if layer["standalone"] is not True:
            raise ProjectError("standalone must be true or omitted")
        result = deepcopy(values)
    else:
        if parent is None:
            raise ProjectError("An inherited stylesheet requires its parent")
        validate(parent)
        result = merge_properties(parent, values)
    # Canonicalization itself decodes and validates the complete native sheet.
    # Avoid decoding the same tree separately just before that operation.
    canonical = cast(
        Json, pickle.loads(_canonical_styles(pickle.dumps(result, protocol=5)))
    )
    cache = _validated.get()
    if cache is not None:
        if len(cache) >= 8192:
            cache.clear()
        cache.add(_validation_key(canonical))
    return canonical


@lru_cache(maxsize=32)
def _canonical_styles(value: bytes) -> bytes:
    # Stylesheets are repeatedly resolved for components in the same application.
    # Cache immutable serialized values, never mutable dictionaries shared by callers.
    return pickle.dumps(encode(decode(pickle.loads(value))), protocol=5)


@lru_cache(maxsize=1)
def _baseline_layer() -> bytes:
    # Package data is immutable during an operation. Keep serialized content so
    # callers never share a mutable stylesheet, even outside resolution_scope.
    data = json.loads(
        files("gorak.templates").joinpath("native_styles.json").read_text()
    )
    return pickle.dumps(data, protocol=5)


def baseline() -> Json:
    return resolve(None, pickle.loads(_baseline_layer()))


def read(path: Path) -> Json:
    if not source_exists(path):
        return empty_delta()
    try:
        value = json.loads(read_source_text(path))
    except (ValueError, OSError) as ex:
        raise ProjectError(f"Cannot read stylesheet: {path}") from ex
    if not is_native_layer(value):
        raise ProjectError(
            "Unsupported stylesheet properties; re-export the application"
        )
    from .image_assets import stylesheet_assets

    resolved: Json = stylesheet_assets(value, path.parent, exporting=False)
    return resolved


def project_styles(root: Path) -> Json:
    layer = read(root / "field_defaults.json")
    return resolve(None if layer.get("standalone") is True else baseline(), layer)


def parent_styles(folder: Path) -> Json:
    return resolve(project_styles(folder.parent), read(folder / "field_defaults.json"))


def resolve_frame(parent: Json, layer: Json) -> Json:
    """A frame can explicitly opt out of stylesheet inheritance."""
    if "absent" in layer:
        if layer != {"absent": True} or layer["absent"] is not True:
            raise ProjectError("An absent stylesheet requires only absent: true")
        return {"absent": True}
    return resolve(parent, layer)


def frame_styles(source: Path) -> Json:
    return resolve_frame(
        parent_styles(source.parent), read(source.with_suffix(".fielddefaults.json"))
    )


def entries(stylesheet: Json) -> list[Json]:
    node = decode(stylesheet)
    counts: dict[str, int] = {}
    result = []
    for group in node.findall("row"):
        name = find_text(group, "clienttext") or ""
        counts[name] = counts.get(name, 0) + 1
        for ordinal, style in enumerate(group.findall("childfields/row"), 1):
            result.append(
                {
                    "group": name,
                    "group_ordinal": counts[name],
                    "style_ordinal": ordinal,
                    "type": style.get(XSI, ""),
                    "sample": encode_value(style),
                }
            )
    return result

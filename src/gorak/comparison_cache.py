"""Content-verified comparison reuse with disposable project metadata storage."""

import hashlib
import inspect
import json
import os
import sys
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import lru_cache, wraps
from importlib.metadata import distributions
from pathlib import Path
from typing import cast
from uuid import uuid4

DIGEST_LENGTH = 64
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 1024


def file_digest(path: Path) -> str:
    result = _file_digest(path)
    persistent = _persistent.get()
    if persistent is not None:
        persistent.observe(path, result)
    return result


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_key(paths: Iterable[Path], root: Path, *, phase: str | None = None) -> str:
    digest = hashlib.sha256()
    from .operation_progress import report

    ordered = sorted(paths)
    if phase:
        report(phase, 0, len(ordered))
    for index, path in enumerate(ordered, 1):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(b"symlink" if path.is_symlink() else b"regular")
        digest.update(file_digest(path).encode("ascii"))
        if path.relative_to(root).parts[0] == ".openroad" and path.suffix == ".xml":
            # Baseline overlay precedence is explicitly ordered by export mtime.
            digest.update(str(path.stat().st_mtime_ns).encode("ascii"))
        digest.update(b"\0")
        if phase:
            report(phase, index, len(ordered))
    return digest.hexdigest()


_entries: ContextVar[dict[tuple[str, str], dict[str, object]] | None] = ContextVar(
    "comparison_entries", default=None
)
_semantics: ContextVar[dict[str, object] | None] = ContextVar(
    "comparison_semantics", default=None
)
_persistent: ContextVar["_ProjectCache | None"] = ContextVar(
    "comparison_project", default=None
)


class _Miss(Exception):
    """Malformed, incompatible or stale disposable cache data."""


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


@lru_cache(maxsize=1)
def implementation_key() -> str:
    """Bind reuse to installed code, templates, Python and dependency versions."""
    package = Path(__file__).parent
    code_paths = sorted(package.rglob("*.py"))
    paths = list(code_paths)
    paths.extend(
        sorted(
            path
            for path in (package / "templates").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    )
    digest = hashlib.sha256(sys.version.encode())
    if getattr(sys, "frozen", False) or not code_paths:
        # Frozen distributions may expose templates without exposing source code.
        digest.update(_file_digest(Path(sys.executable)).encode("ascii"))
    for path in paths:
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(b"\0")
        digest.update(_file_digest(path).encode("ascii"))
    for name, version in sorted(
        (distribution.metadata.get("Name", ""), distribution.version)
        for distribution in distributions()
    ):
        digest.update((name + "\0" + version + "\0").encode())
    return digest.hexdigest()


def storage_path(root: Path) -> Path:
    return root / ".openroad" / "comparison-cache.json"


class _ProjectCache:
    def __init__(self, root: Path, path: Path) -> None:
        self.root = root.resolve()
        self.path = path
        self.implementation = implementation_key()
        self.project = hashlib.sha256(str(self.root).encode()).hexdigest()
        self.records: dict[tuple[str, str], object] = {}
        self.touched: dict[tuple[str, str], None] = {}
        self.observed: dict[str, str | None] = {}
        self.checked: dict[str, str | None] = {}
        self.bindings: dict[tuple[str, str, str, str], str | None] = {}
        self.dirty = False
        self._read()

    def relative(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.root / ".openroad")
        except (OSError, ValueError) as ex:
            raise _Miss from ex
        if len(relative.parts) != 2 or relative.suffix != ".xml":
            raise _Miss
        return relative.as_posix()

    def observe(self, path: Path, digest: str) -> None:
        try:
            relative = self.relative(path)
        except _Miss:
            return
        if self.observed.get(relative) != digest:
            self.checked.pop(relative, None)
        self.observed[relative] = digest

    def bind(self, value: object, *, fresh: bool = False, depth: int = 0) -> None:
        from .sync_plan import DeferredDigest

        if depth > 32:
            return
        if isinstance(value, DeferredDigest):
            try:
                relative = self.relative(value.path)
            except _Miss:
                return
            key = (value.raw, relative, value.tag, value.name)
            if fresh or key not in self.bindings:
                self.bindings[key] = self.observed.get(relative)
        elif isinstance(value, dict):
            for child in value.values():
                self.bind(child, depth=depth + 1)
        elif isinstance(value, list):
            for child in value:
                self.bind(child, depth=depth + 1)

    def current_hash(self, relative: str) -> str | None:
        if relative not in self.checked:
            path = self.root / ".openroad" / relative
            try:
                if self.relative(path) != relative:
                    raise _Miss
                current = _file_digest(path)
                self.observe(path, current)
            except (OSError, _Miss):
                current = None
            self.checked[relative] = current
        return self.checked[relative]

    def _read(self) -> None:
        try:
            if self.path.stat().st_size > MAX_CACHE_BYTES:
                return
            with self.path.open("rb") as stream:
                encoded = stream.read(MAX_CACHE_BYTES + 1)
            if len(encoded) > MAX_CACHE_BYTES:
                return
            document = json.loads(encoded)
            if not isinstance(document, dict) or set(document) != {"data", "checksum"}:
                return
            data = document["data"]
            if hashlib.sha256(_json_bytes(data)).hexdigest() != document["checksum"]:
                return
            if not isinstance(data, dict) or (
                data.get("version"),
                data.get("implementation"),
                data.get("project"),
            ) != (1, self.implementation, self.project):
                return
            records = data.get("entries")
            if not isinstance(records, list) or len(records) > MAX_ENTRIES:
                return
            for record in records:
                if (
                    not isinstance(record, list)
                    or len(record) != 3
                    or not isinstance(record[0], str)
                    or not isinstance(record[1], str)
                    or len(record[0]) > 4096
                    or len(record[1]) > 4096
                    or len(_json_bytes(record)) > MAX_ENTRY_BYTES
                ):
                    raise _Miss
                self.records[(record[0], record[1])] = record[2]
        except (OSError, ValueError, TypeError, RecursionError, _Miss):
            self.records.clear()

    def encode(self, value: object, depth: int = 0) -> object:
        from .sync_plan import DeferredDigest, SemanticDigest

        if depth > 32:
            raise _Miss
        if isinstance(value, SemanticDigest):
            if digests({"value": str(value)}) is None:
                raise _Miss
            return {"digest": str(value)}
        if isinstance(value, DeferredDigest):
            if value.digest is not None:
                return self.encode(SemanticDigest(value.digest), depth + 1)
            relative = self.relative(value.path)
            expected = self.bindings.get((value.raw, relative, value.tag, value.name))
            if expected is None or self.current_hash(relative) != expected:
                raise _Miss
            return {"deferred": [value.raw, relative, value.tag, value.name, expected]}
        if isinstance(value, dict):
            if any(not isinstance(key, str) or len(key) > 4096 for key in value):
                raise _Miss
            return {
                "map": {
                    key: self.encode(child, depth + 1) for key, child in value.items()
                }
            }
        if isinstance(value, list):
            return [self.encode(child, depth + 1) for child in value]
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, str) and len(value) <= 4096:
            return value
        raise _Miss

    def decode(self, value: object, depth: int = 0) -> object:
        from .sync_plan import DeferredDigest, SemanticDigest

        if depth > 32:
            raise _Miss
        if isinstance(value, dict):
            if (
                set(value) == {"digest"}
                and digests({"value": value["digest"]}) is not None
            ):
                return SemanticDigest(value["digest"])
            if set(value) == {"map"} and isinstance(value["map"], dict):
                return {
                    key: self.decode(child, depth + 1)
                    for key, child in value["map"].items()
                }
            if set(value) == {"deferred"}:
                fields = value["deferred"]
                if (
                    not isinstance(fields, list)
                    or len(fields) != 5
                    or any(
                        not isinstance(field, str) or len(field) > 4096
                        for field in fields
                    )
                ):
                    raise _Miss
                raw, relative, tag, name, expected = fields
                if digests({"raw": raw, "file": expected}) is None or tag not in {
                    "APPLICATION",
                    "COMPONENT",
                }:
                    raise _Miss
                path = self.root / ".openroad" / relative
                if self.relative(path) != relative:
                    raise _Miss
                if self.current_hash(relative) != expected:
                    # A fresh baseline scan may already have re-observed this
                    # exact component in a replaced application export.
                    current = semantic(raw)
                    if isinstance(current, (DeferredDigest, SemanticDigest)):
                        return deepcopy(current)
                    raise _Miss
                self.bindings[(raw, relative, tag, name)] = expected
                return DeferredDigest(raw, path, tag, name)
            raise _Miss
        if isinstance(value, list):
            return [self.decode(child, depth + 1) for child in value]
        if (
            value is None
            or isinstance(value, (bool, int))
            or isinstance(value, str)
            and len(value) <= 4096
        ):
            return value
        raise _Miss

    def pull(self, key: tuple[str, str]) -> dict[str, object] | None:
        encoded = self.records.pop(key, None)
        if encoded is None:
            return None
        try:
            if key[0].startswith("components:"):
                # These are independent per-source memo records. A stale
                # component must not discard verified siblings in a large app.
                # Complete inventories deliberately remain all-or-nothing.
                if (
                    not isinstance(encoded, dict)
                    or set(encoded) != {"map"}
                    or not isinstance(encoded["map"], dict)
                ):
                    raise _Miss
                records: dict[str, object] = {}
                for name, record in encoded["map"].items():
                    try:
                        records[name] = self.decode(record, 1)
                    except (OSError, ValueError, TypeError, RecursionError, _Miss):
                        continue
                decoded: object = records
            else:
                decoded = self.decode(encoded)
            if isinstance(decoded, dict):
                self.touched[key] = None
                return decoded
        except (OSError, ValueError, TypeError, RecursionError, _Miss):
            pass
        return None

    def flush(self) -> None:
        entries = _entries.get()
        if entries is None or not self.dirty:
            return
        self.checked.clear()  # Recheck observed bytes at the publication boundary.
        records = dict(self.records)
        for key in self.touched:
            records.pop(key, None)
            if key not in entries:
                continue
            try:
                records[key] = self.encode(entries[key])
            except (OSError, ValueError, TypeError, RecursionError, _Miss):
                continue
        retained: list[list[object]] = []
        size = 512
        for (scope, input_key), value in reversed(records.items()):
            record: list[object] = [scope, input_key, value]
            record_size = len(_json_bytes(record))
            if (
                record_size > MAX_ENTRY_BYTES
                or size + record_size > MAX_CACHE_BYTES - 512
            ):
                continue
            retained.append(record)
            size += record_size
            if len(retained) == MAX_ENTRIES:
                break
        data = {
            "version": 1,
            "implementation": self.implementation,
            "project": self.project,
            "entries": list(reversed(retained)),
        }
        output = _json_bytes(
            {"data": data, "checksum": hashlib.sha256(_json_bytes(data)).hexdigest()}
        )
        if len(output) > MAX_CACHE_BYTES:
            return
        staged = self.path.with_name(f".comparison-cache-{uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                staged,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(output)
            staged.replace(self.path)
        except OSError:
            pass
        finally:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass


@contextmanager
def project_scope(root: Path, *, cache_path: Path | None = None) -> Iterator[None]:
    """Reuse verified JSON metadata and publish atomically after successful work."""
    current = _persistent.get()
    if current is not None and current.root == root.resolve():
        yield
        return
    with scope():
        try:
            persistent = _ProjectCache(root, cache_path or storage_path(root))
        except (OSError, ValueError):
            yield
            return
        token = _persistent.set(persistent)
        try:
            yield
        except BaseException:
            raise
        else:
            persistent.flush()
        finally:
            _persistent.reset(token)


def project_cached[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    signature = inspect.signature(function)

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        root = cast(Path, signature.bind(*args, **kwargs).arguments["root"])
        with project_scope(root):
            return function(*args, **kwargs)

    return wrapped


@contextmanager
def scope() -> Iterator[None]:
    """Release all reused results at the operation boundary, including on failure."""
    if _entries.get() is not None:
        yield
        return
    entries_token = _entries.set({})
    semantics_token = _semantics.set({})
    try:
        yield
    finally:
        _semantics.reset(semantics_token)
        _entries.reset(entries_token)


def active() -> bool:
    return _entries.get() is not None


def load(scope: str, key: str) -> dict[str, object] | None:
    entries = _entries.get()
    data = entries.get((scope, key)) if entries is not None else None
    persistent = _persistent.get()
    if data is None and persistent is not None and entries is not None:
        data = persistent.pull((scope, key))
        if data is not None:
            entries[(scope, key)] = data
    # Independent values keep a caller from changing another comparison's result.
    return deepcopy(data) if data is not None else None


def save(scope: str, key: str, payload: dict[str, object]) -> None:
    entries = _entries.get()
    if entries is None:
        return
    if len(entries) >= MAX_ENTRIES:
        entries.clear()
    entries[(scope, key)] = deepcopy(payload)
    persistent = _persistent.get()
    if persistent is not None:
        persistent.bind(payload)
        persistent.touched.pop((scope, key), None)
        persistent.touched[(scope, key)] = None
        persistent.dirty = True


def semantic(raw: str) -> object:
    entries = _semantics.get()
    return entries.get(raw) if entries is not None else None


def remember_semantic(raw: str, digest: object) -> None:
    entries = _semantics.get()
    if entries is not None:
        if len(entries) >= 32768:
            entries.clear()
        entries[raw] = digest
    persistent = _persistent.get()
    if persistent is not None:
        persistent.bind(digest, fresh=True)


def digests(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or not isinstance(digest, str)
        or len(digest) != DIGEST_LENGTH
        or any(char not in "0123456789abcdef" for char in digest)
        for key, digest in value.items()
    ):
        return None
    return value


def project_key(root: Path) -> str:
    """Hash source bytes, including dependencies; never trust size/mtime alone."""
    paths: list[Path] = []
    for folder, dirs, files in os.walk(root):
        if Path(folder) == root:
            dirs[:] = [name for name in dirs if name not in {".git", ".openroad"}]
        if any((Path(folder) / name).is_symlink() for name in dirs):
            raise OSError("Comparison cache does not follow directory symlinks")
        paths.extend(Path(folder) / name for name in files)
    cache = root / ".openroad"
    paths.extend(cache.glob("*/*.xml"))
    tracking = cache / "tracked-applications.json"
    if tracking.exists():
        paths.append(tracking)
    return content_key(paths, root, phase="Checking source and baseline bytes")


def shared_key(root: Path, folder: Path) -> str:
    paths: list[Path] = []
    for parent in (root, folder):
        stylesheet = parent / "field_defaults.json"
        if stylesheet.exists():
            paths.append(stylesheet)
        paths.extend(path for path in (parent / "images").rglob("*") if path.is_file())
    return content_key(paths, root)

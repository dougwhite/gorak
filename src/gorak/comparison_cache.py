"""Disposable content-addressed comparison results; never synchronization authority."""

import hashlib
import json
import os
import sys
from collections.abc import Iterable
from functools import lru_cache
from importlib.metadata import distributions
from pathlib import Path

DIGEST_LENGTH = 64
MAX_CACHE_BYTES = 16 * 1024 * 1024


def file_digest(path: Path) -> str:
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


@lru_cache(maxsize=1)
def implementation_key() -> str:
    """Invalidate on installed Python implementation or packaged template changes."""
    root = Path(__file__).parent
    source = content_key(
        [
            *root.glob("*.py"),
            *(p for p in (root / "templates").rglob("*") if p.is_file()),
        ],
        root,
    )

    environment = sorted(
        (str(dist.metadata.get("Name", "")), str(dist.version))
        for dist in distributions()
    )
    return hashlib.sha256(
        (source + sys.version + repr(environment)).encode()
    ).hexdigest()


def cache_directory() -> Path:
    override = os.environ.get("GORAK_COMPARISON_CACHE_DIR")
    if override:
        return Path(override)
    base = (
        os.environ.get("LOCALAPPDATA")
        if os.name == "nt"
        else os.environ.get("XDG_CACHE_HOME")
    )
    return (Path(base) if base else Path.home() / ".cache") / "gorak" / "comparisons"


def cache_path(scope: str, key: str) -> Path:
    name = hashlib.sha256((implementation_key() + scope + key).encode()).hexdigest()
    return cache_directory() / f"{name}.json"


def load(scope: str, key: str) -> dict[str, object] | None:
    try:
        path = cache_path(scope, key)
        with path.open("rb") as stream:
            data = stream.read(MAX_CACHE_BYTES + 1)
        if len(data) > MAX_CACHE_BYTES:
            return None
        envelope = json.loads(data)
        if (
            not isinstance(envelope, dict)
            or envelope.get("scope") != scope
            or envelope.get("input") != key
        ):
            return None
        payload = envelope["payload"]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        if envelope["sha256"] != hashlib.sha256(encoded).hexdigest():
            return None
        if not isinstance(payload, dict):
            return None
        try:
            path.touch()  # Keep hot baselines when obsolete cache versions are pruned.
        except OSError:
            pass
        return payload
    except (OSError, ValueError, TypeError, KeyError):
        return None


def save(scope: str, key: str, payload: dict[str, object]) -> None:
    from uuid import uuid4

    temporary = None
    try:
        path = cache_path(scope, key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        data = json.dumps(
            {
                "scope": scope,
                "input": key,
                "payload": payload,
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        ).encode()
        if len(data) > MAX_CACHE_BYTES:
            return
        temporary = path.with_name(f".{uuid4().hex}.tmp")
        with temporary.open("xb") as stream:
            stream.write(data)
        temporary.replace(path)
        # Disposable entries are bounded; pruning never affects source or baselines.
        entries = sorted(
            path.parent.glob("*.json"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
        retained_bytes = 0
        for index, entry in enumerate(entries):
            retained_bytes += entry.stat().st_size
            if index >= 1024 or retained_bytes > 128 * 1024 * 1024:
                entry.unlink(missing_ok=True)

    except OSError:
        pass  # Read-only or unavailable caches never prevent a fresh comparison.
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


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

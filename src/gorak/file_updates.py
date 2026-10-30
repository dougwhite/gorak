"""File updates for stylesheet tooling and experimental snapshot verification."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from .project import ProjectError


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_digests(files: list[tuple[str, Path]]) -> dict[str, str]:
    result = {}
    for relative, path in files:
        # Enumeration and hashing may be separated by other files. Recheck the
        # symlink policy when consuming each source, including in worker threads.
        if path.is_symlink():
            raise ProjectError(
                f"Sync does not support symlinked project source: {relative}"
            )
        result[relative] = file_digest(path)
    return result


def fingerprint(root: Path) -> dict[str, str]:
    files = []
    pending = [root]
    while pending:
        folder = pending.pop()
        # Windows directory enumeration already supplies file type information.
        # Reuse it instead of issuing two extra stat calls per source file.
        # Contents are still read and hashed on every pass, regardless of mtime.
        with os.scandir(folder) as entries:
            for entry in entries:
                if folder == root and entry.name in {".git", ".openroad"}:
                    continue
                path = Path(entry.path)
                relative = path.relative_to(root)
                if entry.is_symlink():
                    raise ProjectError(
                        f"Sync does not support symlinked project source: {relative}"
                    )
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files.append((relative.as_posix(), path))
    if len(files) < 512:
        result = _source_digests(files)
    else:
        # Bound both open files and concurrent read buffers. Small batches avoid
        # one future per file while overlapping Windows file-open/read latency.
        with ThreadPoolExecutor(max_workers=4) as workers:
            result = {}
            for digests in workers.map(
                _source_digests,
                (files[index : index + 64] for index in range(0, len(files), 64)),
            ):
                result.update(digests)
    result.update(baseline_fingerprint(root))
    return result


def baseline_fingerprint(root: Path) -> dict[str, str]:
    """Hash tracking state without rereading the editable checkout."""
    result = {}
    for path in (root / ".openroad").glob("*/*"):
        if not path.is_file() or not (
            path.suffix == ".xml" or path.name.endswith(".receipt.json")
        ):
            continue
        if path.parent.name not in {"pulls", "pushes", "imports", "runs"}:
            result[path.relative_to(root).as_posix()] = file_digest(path)
    for name in ["sync-target.json", "tracked-applications.json"]:
        path = root / ".openroad" / name
        if path.exists():
            result[path.relative_to(root).as_posix()] = file_digest(path)
    return result


def apply_files(
    root: Path,
    changes: dict[Path, bytes | None],
    recovery: Path,
    expected: dict[str, str] | None = None,
    *,
    baseline_only: bool = False,
) -> None:
    """Keep before-images and roll back only files still matching our own writes."""
    if baseline_only:
        if expected is None or any(
            path.relative_to(root).parts[0] != ".openroad" for path in changes
        ):
            raise ProjectError("Baseline installation requires tracking-only changes")
        expected = {k: v for k, v in expected.items() if k.startswith(".openroad/")}
    current = baseline_fingerprint if baseline_only else fingerprint
    if expected is not None and current(root) != expected:
        raise ProjectError("File changed before pull installation; retry")
    originals = {path: path.read_bytes() if path.exists() else None for path in changes}
    if expected is not None:
        for path, content in originals.items():
            actual = (
                hashlib.sha256(content).hexdigest() if content is not None else None
            )
            if actual != expected.get(path.relative_to(root).as_posix()):
                raise ProjectError(f"File changed before pull installation: {path}")
    for path, content in originals.items():
        if content is not None:
            backup = recovery / "before" / path.relative_to(root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(content)
    journal = {
        str(path.relative_to(root)): "delete" if data is None else "write"
        for path, data in changes.items()
    }
    (recovery / "changes.json").write_text(json.dumps(journal, indent=2))
    applied = []
    try:
        for path, content in changes.items():
            if (path.read_bytes() if path.exists() else None) != originals[path]:
                raise ProjectError(f"File changed during pull: {path}")
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                staged = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
                try:
                    staged.write_bytes(content)
                    staged.replace(path)
                finally:
                    staged.unlink(missing_ok=True)
            applied.append(path)
    except Exception:
        for path in reversed(applied):
            if (path.read_bytes() if path.exists() else None) != changes[path]:
                continue  # Never overwrite a concurrent external edit during recovery.
            original = originals[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        raise

"""Private readable-input snapshots for exact comparison provenance."""

import hashlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree
from tempfile import TemporaryDirectory

from lxml import etree

from .project import ProjectError

COMPANIONS = (".wml", ".fielddefaults.json", ".queries.json", ".icons.json")


def source_paths(source: Path, *, application: bool = False) -> list[Path]:
    paths = [source]
    if not application:
        paths.extend(
            path
            for suffix in COMPANIONS
            if (path := source.with_suffix(suffix)).exists()
        )
    return paths


class InputSnapshots:
    def __init__(self) -> None:
        self.temporary: TemporaryDirectory[str] | None = None
        self.root: Path | None = None
        self.proof: Mapping[str, str] | None = None
        self.app: str | None = None
        self.shared: set[Path] = set()
        self.digests: dict[str, str] = {}

    def close(self) -> None:
        if self.temporary is not None:
            self.temporary.cleanup()

    def target(self, root: Path) -> Path:
        if self.root is not None and self.root != root:
            raise ProjectError("Comparison input snapshot belongs to another project")
        self.root = root
        if self.temporary is None:
            self.temporary = TemporaryDirectory(prefix="gorak-comparison-")
        return Path(self.temporary.name)

    def copy(self, path: Path, root: Path, target: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise ProjectError(f"Comparison input is not a regular file: {path}")
        relative = path.relative_to(root)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with path.open("rb") as source, destination.open("wb") as output:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                output.write(chunk)
        value = digest.hexdigest()
        name = relative.as_posix()
        if self.proof is not None and self.proof.get(name) != value:
            raise ProjectError("Source changed during comparison; retry")
        self.digests[name] = value

    def copy_shared(self, parent: Path, root: Path, target: Path) -> None:
        if parent in self.shared:
            return
        paths: list[Path] = []
        defaults = parent / "field_defaults.json"
        if defaults.exists():
            paths.append(defaults)
        images = parent / "images"
        if images.is_symlink():
            raise ProjectError(f"Comparison input is symlinked: {images}")
        for path in images.rglob("*"):
            if path.is_symlink():
                raise ProjectError(f"Comparison input is symlinked: {path}")
            if path.is_dir():
                # Existence of obsolete bitmap sidecars also affects validation.
                (target / path.relative_to(root)).mkdir(parents=True, exist_ok=True)
            else:
                paths.append(path)
        if self.proof is not None:
            prefix = images.relative_to(root).as_posix() + "/"
            expected = {
                name
                for name in self.proof
                if name == defaults.relative_to(root).as_posix()
                or name.startswith(prefix)
            }
            if expected != {path.relative_to(root).as_posix() for path in paths}:
                raise ProjectError(
                    "Source dependencies changed during comparison; retry"
                )
        for path in paths:
            self.copy(path, root, target)
        self.shared.add(parent)

    @contextmanager
    def capture(
        self, root: Path, source: Path, *, application: bool, baseline_raw: str | None
    ) -> Iterator[Mapping[str, str]]:
        target = self.target(root)
        app = source.parent.name
        if self.app is not None and self.app != app:
            rmtree(target / self.app, ignore_errors=True)
            self.shared.discard(root / self.app)
            self.digests = {
                name: value
                for name, value in self.digests.items()
                if not name.startswith(self.app + "/")
            }
        self.app = app
        self.copy_shared(root, root, target)
        self.copy_shared(source.parent, root, target)
        paths = source_paths(source, application=application)
        if self.proof is not None:
            expected = {source.relative_to(root).as_posix()}
            if not application:
                expected.update(
                    path.relative_to(root).as_posix()
                    for suffix in COMPANIONS
                    if (path := source.with_suffix(suffix)).relative_to(root).as_posix()
                    in self.proof
                )
            if expected != {path.relative_to(root).as_posix() for path in paths}:
                raise ProjectError("Source companions changed during comparison; retry")
        try:
            for path in paths:
                self.copy(path, root, target)
            token = _bound.set(BoundInputs(root, target, baseline_raw))
            try:
                yield self.digests
            finally:
                _bound.reset(token)
        finally:
            for path in paths:
                (target / path.relative_to(root)).unlink(missing_ok=True)


@dataclass(frozen=True)
class BoundInputs:
    root: Path
    target: Path
    baseline_raw: str | None


_snapshots: ContextVar[InputSnapshots | None] = ContextVar(
    "comparison_inputs", default=None
)
_bound: ContextVar[BoundInputs | None] = ContextVar(
    "comparison_input_binding", default=None
)


@contextmanager
def scope() -> Iterator[None]:
    if _snapshots.get() is not None:
        yield
        return
    snapshots = InputSnapshots()
    token = _snapshots.set(snapshots)
    try:
        yield
    finally:
        _snapshots.reset(token)
        snapshots.close()


def set_proof(root: Path, digests: Mapping[str, str] | None) -> None:
    snapshots = _snapshots.get()
    if snapshots is not None:
        snapshots.root = root
        snapshots.proof = digests


@contextmanager
def capture(
    root: Path,
    source: Path,
    *,
    application: bool = False,
    baseline_raw: str | None = None,
    verified_digests: Mapping[str, str] | None = None,
) -> Iterator[Mapping[str, str]]:
    with scope():
        snapshots = _snapshots.get()
        assert snapshots is not None
        if verified_digests is not None:
            set_proof(root, verified_digests)
        with snapshots.capture(
            root, source, application=application, baseline_raw=baseline_raw
        ) as digests:
            yield digests


def path_for_read(path: Path) -> Path:
    bound = _bound.get()
    return path if bound is None else bound.target / path.relative_to(bound.root)


def bound() -> bool:
    return _bound.get() is not None


def verify_baseline(node: etree._Element | None) -> None:
    bound = _bound.get()
    if bound is None:
        return
    actual = (
        hashlib.sha256(
            etree.tostring(node, encoding="utf-8", with_tail=False)
        ).hexdigest()
        if node is not None
        else None
    )
    if actual != bound.baseline_raw:
        raise ProjectError("Baseline changed during source comparison; retry")

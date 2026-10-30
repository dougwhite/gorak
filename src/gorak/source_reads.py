"""Operation-scoped immutable bytes for readable source reconstruction."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_bound: ContextVar[tuple[Path, dict[Path, bytes]] | None] = ContextVar(
    "source_read_bytes", default=None
)


@contextmanager
def captured(root: Path, values: dict[Path, bytes]) -> Iterator[None]:
    token = _bound.set((root, values))
    try:
        yield
    finally:
        _bound.reset(token)


def read_bytes(path: Path) -> bytes:
    bound = _bound.get()
    if bound is not None and path.is_relative_to(bound[0]):
        try:
            return bound[1][path]
        except KeyError:
            raise FileNotFoundError(path) from None
    return path.read_bytes()


def read_text(path: Path) -> str:
    return read_bytes(path).decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def is_file(path: Path) -> bool:
    bound = _bound.get()
    if bound is not None and path.is_relative_to(bound[0]):
        return path in bound[1]
    return path.is_file()


def exists(path: Path) -> bool:
    bound = _bound.get()
    if bound is not None and path.is_relative_to(bound[0]):
        # A directory at a source-file location must still fail validation;
        # a newly created ordinary file is not part of the captured inputs.
        return path in bound[1] or path.is_dir()
    return path.exists()

"""Bounded native prefetch, with ordered consumption and disk-backed results."""

from collections.abc import Callable, Generator, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from .errors import ProjectError


@contextmanager
def prefetched_exports(
    names: Sequence[str],
    workers: int,
    backup: Callable[[str, Path], None],
) -> Iterator[Iterator[tuple[str, Path]]]:
    """Overlap native exports with the caller's sequential conversion.

    Only distinct applications may be in flight. On failure or cancellation,
    cancel queued jobs and join running jobs before deleting their files.
    """
    if workers < 1:
        raise ProjectError("GORAK_EXPORT_WORKERS must be a positive integer")
    if len({name.casefold() for name in names}) != len(names):
        raise ProjectError("Duplicate applications in export batch")
    with TemporaryDirectory(prefix="gorak-export-") as temporary:
        pool = ThreadPoolExecutor(max_workers=min(workers, len(names) or 1))
        pending: dict[int, Future[Path]] = {}
        entries = iter(enumerate(names))

        def fetch(index: int, name: str) -> Path:
            path = Path(temporary) / f"{index}.xml"
            backup(name, path)
            return path

        def submit() -> None:
            item = next(entries, None)
            if item is not None:
                index, name = item
                pending[index] = pool.submit(fetch, index, name)

        def consume() -> Generator[tuple[str, Path], None, None]:
            for index, name in enumerate(names):
                path = pending.pop(index).result()
                submit()
                try:
                    yield name, path
                finally:
                    path.unlink(missing_ok=True)

        stream = consume()
        try:
            for _ in range(min(workers, len(names))):
                submit()
            yield stream
        finally:
            try:
                stream.close()
            finally:
                for future in pending.values():
                    future.cancel()
                pool.shutdown(wait=True, cancel_futures=True)

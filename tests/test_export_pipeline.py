from pathlib import Path
from threading import Barrier, Event, Lock

import pytest

from gorak.export_pipeline import prefetched_exports
from gorak.project import ProjectError


def test_prefetch_is_bounded_ordered_and_overlaps_conversion() -> None:
    first_batch = Barrier(2, timeout=5)
    third = Event()
    started: list[str] = []
    lock = Lock()
    paths: list[Path] = []

    def backup(name: str, path: Path) -> None:
        with lock:
            started.append(name)
            paths.append(path)
        if name in {"a", "b"}:
            first_batch.wait()
        if name == "c":
            third.set()
        path.write_text(name)

    with prefetched_exports(["a", "b", "c", "d"], 2, backup) as pending:
        name, path = next(pending)
        assert name == "a" and path.read_text() == "a"
        assert third.wait(5)  # Prefetch runs while this consumer is paused.
        assert set(started) == {"a", "b", "c"}  # d cannot be queued yet.
        assert [(name, path.read_text()) for name, path in pending] == [
            ("b", "b"),
            ("c", "c"),
            ("d", "d"),
        ]
    assert all(not path.exists() for path in paths)


def test_worker_failure_joins_other_workers_before_cleanup() -> None:
    barrier = Barrier(2, timeout=5)
    finished = Event()
    paths: list[Path] = []

    def backup(name: str, path: Path) -> None:
        paths.append(path)
        barrier.wait()
        if name == "a":
            raise ProjectError("native failed")
        assert path.parent.is_dir()
        path.write_text(name)
        finished.set()

    with pytest.raises(ProjectError, match="native failed"):
        with prefetched_exports(["a", "b", "c"], 2, backup) as pending:
            next(pending)
    assert finished.is_set()
    assert len(paths) == 2 and all(not p.parent.exists() for p in paths)


def test_consumer_failure_cleans_up_and_does_not_schedule_entire_batch() -> None:
    paths: list[Path] = []

    def backup(name: str, path: Path) -> None:
        paths.append(path)
        path.write_text(name)

    with pytest.raises(RuntimeError, match="conversion failed"):
        with prefetched_exports(["a", "b", "c", "d"], 1, backup) as pending:
            next(pending)
            raise RuntimeError("conversion failed")
    assert len(paths) <= 2
    assert all(not p.parent.exists() for p in paths)


@pytest.mark.parametrize("names,workers", [(["a", "A"], 2), (["a"], 0)])
def test_invalid_batch_never_starts_workers(names: list[str], workers: int) -> None:
    def backup(name: str, path: Path) -> None:
        pytest.fail("Unexpected export")

    with pytest.raises(ProjectError):
        with prefetched_exports(names, workers, backup):
            pass

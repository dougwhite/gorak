"""Phase progress and periodic activity reports without contaminating JSON output."""

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, Lock, Thread
from time import monotonic


class OperationProgress:
    def __init__(self, emit: Callable[[str], None]) -> None:
        self.emit = emit
        self.lock = Lock()
        self.message = "Starting"
        self.key: tuple[str, int | None] | None = None
        self.started = monotonic()

    def update(self, phase: str, done: int | None, total: int | None) -> None:
        percent = (
            None
            if done is None or total is None
            else (100 * done // total if total else 100)
        )
        message = (
            phase
            if percent is None
            else f"{phase}: {percent}% ({done}/{total}); {100 - percent}% of phase remaining"
        )
        with self.lock:
            self.message = message
            key = (phase, percent)
            if key != self.key:
                self.key = key
                self.emit(message)

    def heartbeat(self) -> None:
        with self.lock:
            self.emit(
                f"Still running ({int(monotonic() - self.started)}s elapsed): {self.message}"
            )


_current: ContextVar[OperationProgress | None] = ContextVar(
    "operation_progress", default=None
)


def report(phase: str, done: int | None = None, total: int | None = None) -> None:
    progress = _current.get()
    if progress is not None:
        progress.update(phase, done, total)


@contextmanager
def progress_scope(
    operation: str,
    emit: Callable[[str], None] | None = None,
    *,
    interval: float = 10,
) -> Iterator[None]:
    """Heartbeat means the command is alive, not that an external call is advancing."""
    if _current.get() is not None:
        yield
        return
    if interval <= 0:
        raise ValueError("Progress interval must be positive")
    progress = OperationProgress(
        emit or (lambda message: print(message, file=sys.stderr, flush=True))
    )
    stop = Event()

    def heartbeat() -> None:
        while not stop.wait(interval):
            progress.heartbeat()

    token = _current.set(progress)
    thread = Thread(target=heartbeat, name="gorak-progress", daemon=True)
    try:
        report(f"{operation}: starting (percentages apply to each phase)")
        thread.start()
        yield
    finally:
        stop.set()
        if thread.ident is not None:
            thread.join()
        _current.reset(token)

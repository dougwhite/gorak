"""Throttled progress for bulk source projection."""

from collections.abc import Callable
from time import monotonic


def duration(seconds: float) -> str:
    seconds = max(0, round(seconds))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


class EncodingProgress:
    def __init__(self, app: str, total: int, emit: Callable[[str], None] | None):
        self.app = app
        self.total = total
        self.emit = emit
        self.started = self.updated = monotonic()
        if total > 10 and emit:
            emit(f"Encoding {app}: 0/{total} components")

    def before(self, name: str) -> None:
        if self.total <= 10 and self.emit:
            self.emit(f"Encoding component {self.app}!{name}")

    def completed(self, count: int) -> None:
        if self.total <= 10 or self.emit is None:
            return
        now = monotonic()
        if count != self.total and now - self.updated < 5:
            return
        elapsed = now - self.started
        text = f"Encoding {self.app}: {count}/{self.total} components, {duration(elapsed)} elapsed"
        if count < self.total:
            text += (
                f", about {duration(elapsed * (self.total - count) / count)} remaining"
            )
        self.emit(text)
        self.updated = now

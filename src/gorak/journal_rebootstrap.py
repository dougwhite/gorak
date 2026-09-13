"""Publish a fresh consumer after verified full observation, retaining old state."""

import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .journal_reconcile import flush_directory
from .project import ProjectError


def publish_consumer(root: Path, operation: Path) -> None:
    """Caller holds the project lock and has closed both SQLite connections.

    Invalidate the old snapshot before replacing the consumer. An interruption
    between those steps leaves no snapshot eligible for reuse.
    """
    directory = root / ".openroad"
    current = directory / "journal.sqlite3"
    pointer = directory / "journal-snapshot.json"
    # Gorak uses rollback-journal SQLite. Do not replace a DB with live sidecars.
    if any(
        Path(str(current) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
    ):
        raise ProjectError(
            "Journal sidecars present; close other users before rebootstrap"
        )
    archive = operation / "previous"
    archive.mkdir()
    if current.exists():
        with closing(
            sqlite3.connect(current.as_uri() + "?mode=ro", uri=True)
        ) as source:
            with closing(sqlite3.connect(archive / "journal.sqlite3")) as destination:
                source.backup(destination)
    if pointer.exists():
        shutil.copyfile(pointer, archive / "journal-snapshot.json")
    for path in archive.iterdir():
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
    flush_directory(archive)
    flush_directory(operation)
    staged = operation / "journal.sqlite3"
    with staged.open("rb") as stream:
        os.fsync(stream.fileno())
    pointer.unlink(missing_ok=True)
    flush_directory(directory)
    staged.replace(current)
    flush_directory(directory)

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from gorak.journal_rebootstrap import publish_consumer
from gorak.project import ProjectError


def setup(tmp_path: Path) -> tuple[Path, Path]:
    directory = tmp_path / ".openroad"
    directory.mkdir()
    operation = directory / "journal-snapshots" / "operation"
    operation.mkdir(parents=True)
    for path, value in [
        (directory / "journal.sqlite3", "old"),
        (operation / "journal.sqlite3", "new"),
    ]:
        with sqlite3.connect(path) as store:
            store.execute("create table consumer (id text)")
            store.execute("insert into consumer values (?)", (value,))
    (directory / "journal-snapshot.json").write_text("old snapshot")
    return directory, operation


def identity(path: Path) -> str:
    with sqlite3.connect(path) as store:
        return str(store.execute("select id from consumer").fetchone()[0])


def test_archive_and_replace_consumer(tmp_path: Path) -> None:
    directory, operation = setup(tmp_path)
    publish_consumer(tmp_path, operation)
    assert identity(directory / "journal.sqlite3") == "new"
    assert identity(operation / "previous/journal.sqlite3") == "old"
    assert (operation / "previous/journal-snapshot.json").read_text() == "old snapshot"
    assert not (directory / "journal-snapshot.json").exists()


def test_replace_failure_leaves_no_reusable_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, operation = setup(tmp_path)

    def fail(*args: Any) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="replace failed"):
        publish_consumer(tmp_path, operation)
    assert identity(directory / "journal.sqlite3") == "old"
    assert not (directory / "journal-snapshot.json").exists()
    assert identity(operation / "previous/journal.sqlite3") == "old"


def test_live_sidecar_rejected_without_changes(tmp_path: Path) -> None:
    directory, operation = setup(tmp_path)
    (directory / "journal.sqlite3-wal").touch()
    with pytest.raises(ProjectError, match="sidecars"):
        publish_consumer(tmp_path, operation)
    assert (directory / "journal-snapshot.json").read_text() == "old snapshot"
    assert identity(directory / "journal.sqlite3") == "old"

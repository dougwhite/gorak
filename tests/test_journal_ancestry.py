from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gorak import journal_ancestry
from gorak.database import OdbcSettings
from gorak.journal_ancestry import (
    load_ancestry,
    parse_entities,
    read_ancestry,
    write_ancestry,
)
from gorak.journal_mapping import Entity
from gorak.project import ProjectError

SETTINGS = OdbcSettings("driver", "host", "port", "source_db", "user", "secret")


def test_ancestry_roundtrip(tmp_path: Path) -> None:
    entities = (Entity(1, 0, 0, "example", "appsource"),)
    path = tmp_path / "ancestry.json"
    write_ancestry(path, entities)
    assert load_ancestry(path) == entities
    with pytest.raises(FileExistsError):
        write_ancestry(path, ())
    path.unlink()
    write_ancestry(path, None)
    assert load_ancestry(path) is None


@pytest.mark.parametrize(
    "rows",
    [
        {},
        [[1, 0, 0, "app", "appsource"]] * 2,
        [[True, 0, 0, "app", "appsource"]],
        [[1, 0, 0, None, "appsource"]],
        [[1, -1, 0, "app", "appsource"]],
        [[1, 0, 0, "app"]],
    ],
)
def test_invalid_history_rejected(rows: object) -> None:
    with pytest.raises(ValueError):
        parse_entities(rows)


def test_read_is_bounded_and_disposes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_ancestry, "MAX_SNAPSHOT_ENTITIES", 1)
    engine, result = MagicMock(), MagicMock()
    result.__iter__.return_value = iter(
        [(1, 0, 0, "example", "appsource"), (2, 0, 0, "other", "appsource")]
    )
    engine.connect.return_value.__enter__.return_value.execute.return_value = result
    assert read_ancestry(SETTINGS, engine_factory=lambda _: engine) is None
    result.close.assert_called_once()
    engine.dispose.assert_called_once()
    query = engine.connect.return_value.__enter__.return_value.execute.call_args.args[0]
    assert "select first 2" in str(query)
    assert "text_string" not in str(query)


def test_bad_database_rows_abort_and_dispose() -> None:
    engine, result = MagicMock(), MagicMock()
    result.__iter__.return_value = iter([(None, 0, 0, "example", "appsource")])
    engine.connect.return_value.__enter__.return_value.execute.return_value = result
    with pytest.raises(ProjectError, match="Invalid entity ancestry"):
        read_ancestry(SETTINGS, engine_factory=lambda _: engine)
    engine.dispose.assert_called_once()

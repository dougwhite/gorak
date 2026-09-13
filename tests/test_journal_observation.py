from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from gorak.database import OdbcSettings
from gorak.journal_observation import observe_journal
from gorak.project import ProjectError


def observe(rows: list[tuple[Any, ...]]) -> tuple[Any, MagicMock]:
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.side_effect = [[], rows]
    result = observe_journal(
        OdbcSettings("driver", "host", "port", "db", "user", "secret"),
        engine_factory=lambda _: engine,
    )
    return result, engine


@pytest.mark.parametrize("count,maximum", [(0, None), (2, 10)])
def test_committed_observation(count: int, maximum: int | None) -> None:
    identity = str(uuid4())
    result, engine = observe([(2, identity, "capture_only ", count, maximum)])
    assert result.installation_id == identity
    assert result.event_count == count
    assert result.max_event_id == maximum
    engine.dispose.assert_called_once()


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [(2, "invalid", "capture_only", 0, None)],
        [(3, str(uuid4()), "capture_only", 0, None)],
        [(2, str(uuid4()), "other", 0, None)],
        [(2, str(uuid4()), "capture_only", -1, None)],
        [(2, str(uuid4()), "capture_only", 1, None)],
        [(2, str(uuid4()), "capture_only", 0, 1)],
        [(2, str(uuid4()), "capture_only", 3, 2)],
    ],
)
def test_invalid_observation_rejected(rows: list[tuple[Any, ...]]) -> None:
    with pytest.raises(ProjectError, match="Invalid journal observation"):
        observe(rows)


def test_connection_failure_disposes_engine() -> None:
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("disconnected")
    with pytest.raises(RuntimeError, match="disconnected"):
        observe_journal(
            OdbcSettings("driver", "host", "port", "db", "user", "secret"),
            engine_factory=lambda _: engine,
        )
    engine.dispose.assert_called_once()

from dataclasses import replace
from typing import Any

import pytest

from gorak.affected_source import revision_delta, select_affected
from gorak.database import OdbcSettings
from gorak.installation import FIELDS
from gorak.revision_observation import BoundRevisionSample, RevisionSample

SETTINGS = OdbcSettings("driver", "host", "port", "db", "user", "password")
OLD = BoundRevisionSample("generation", "parent", RevisionSample((("s", "p", 10),), 1))


def current(n: int) -> BoundRevisionSample:
    return replace(OLD, sample=RevisionSample((("s", "p", n),), 1))


def event(identity: int, table: str = "ii_entities") -> list[object]:
    side: list[object] = [12, 11, 0, -1, None, None, "probe", "proc4glsource"]
    assert len(side) == len(FIELDS)
    return [identity, table, "u", *side, *side]


class Engine:
    def __init__(self, rows: list[list[object]]) -> None:
        self.rows = rows
        self.queries: list[str] = []
        self.disposed = False
        self.closed = False

    def connect(self) -> "Engine":
        return self

    def __enter__(self) -> "Engine":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def execute(self, query: Any, params: Any = None) -> "Engine":
        self.queries.append(str(query))
        if params:
            assert params == {"maximum": 100}
        return self

    def fetchmany(self, n: int) -> list[list[object]]:
        return self.rows[:n]

    def close(self) -> None:
        self.closed = True

    def dispose(self) -> None:
        self.disposed = True


def test_exact_range_preserves_both_sides_and_orders_locally() -> None:
    rows = [event(105), event(103)]
    rows[0][3] = 13
    engine = Engine(rows)
    result = select_affected(SETTINGS, OLD, current(12), 100, lambda _: engine)
    assert result.fallback is None
    assert result.object_ids == (12, 13)
    assert [e.event_id for e in result.events] == [103, 105]
    assert result.maximum == 105
    assert "select first 3" in engine.queries[-1]
    assert "order by" not in engine.queries[-1]
    assert engine.disposed and engine.closed


@pytest.mark.parametrize(
    "rows", [[], [event(105)], [event(105), event(106), event(107)]]
)
def test_late_lower_commit_pruning_or_racing_insert_requires_full(
    rows: list[list[object]],
) -> None:
    engine = Engine(rows)
    result = select_affected(SETTINGS, OLD, current(12), 100, lambda _: engine)
    assert result.fallback == "event_count_disagrees_with_revisions"
    assert result.events == () and result.object_ids == ()


def test_rollback_has_no_delta_and_no_query() -> None:
    def forbidden(_: Any) -> Any:
        raise AssertionError("No query on unchanged vector")

    assert select_affected(SETTINGS, OLD, OLD, 100, forbidden).maximum == 100


@pytest.mark.parametrize(
    "sample",
    [
        current(9),
        replace(OLD, revision_id="new"),
        replace(OLD, parent_installation_id="new"),
        replace(OLD, sample=RevisionSample((), 0)),
        replace(OLD, sample=RevisionSample(None, 4097)),
    ],
)
def test_invalid_continuity(sample: BoundRevisionSample) -> None:
    assert revision_delta(OLD, sample) is None


def test_new_lane_and_reused_monotonic_lane_count_events() -> None:
    sample = replace(OLD, sample=RevisionSample((("s", "p", 12), ("s", "q", 3)), 2))
    assert revision_delta(OLD, sample) == 5


@pytest.mark.parametrize(
    "fault", ["duplicate", "shared", "missing", "invalid", "budget"]
)
def test_unsupported_candidates_discard_entire_selection(fault: str) -> None:
    rows = [event(101), event(102)]
    if fault == "duplicate":
        rows[1] = event(101)
    elif fault == "shared":
        rows[1] = event(102, "ii_stored_strings")
    elif fault == "missing":
        rows[1][3] = rows[1][3 + len(FIELDS)] = None
    elif fault == "invalid":
        rows[1][3] = "12"
    engine = Engine(rows)
    result = select_affected(
        SETTINGS, OLD, current(5000 if fault == "budget" else 12), 100, lambda _: engine
    )
    assert result.fallback
    assert result.events == () and result.object_ids == ()
    if fault == "budget":
        assert engine.queries == []


def test_update_with_missing_old_identity_cannot_hide_previous_owner() -> None:
    row = event(101)
    row[3] = None
    engine = Engine([row])
    result = select_affected(SETTINGS, OLD, current(11), 100, lambda _: engine)
    assert result.fallback == "missing_object_identity"
    assert result.history_queries == 1

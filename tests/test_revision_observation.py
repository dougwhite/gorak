import re
import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from gorak.database import OdbcSettings
from gorak.project import ProjectError
from gorak.revision_observation import observe_revisions

SETTINGS = OdbcSettings("driver", "host", "port", "source_db", "user", "secret")


def server(rows: list[tuple[Any, ...]]) -> tuple[sqlite3.Connection, MagicMock]:
    db = sqlite3.connect(":memory:")
    db.execute('attach database ":memory:" as "$ingres"')
    db.execute('create table "$ingres".counter (server_id,session_id,revision)')
    db.executemany('insert into "$ingres".counter values (?,?,?)', rows)
    engine = MagicMock()

    def execute(statement: Any) -> Any:
        sql = str(statement)
        if sql.startswith("set lockmode"):
            assert 'on "$ingres".counter' in sql
            assert "level=mvcc, readlock=shared" in sql
            return []
        match = re.match(r"select first (\d+) ", sql)
        assert match
        return db.execute("select " + sql[match.end() :] + " limit " + match[1])

    engine.connect.return_value.__enter__.return_value.execute.side_effect = execute
    return db, engine


@pytest.mark.parametrize(
    "count,complete", [(0, True), (3, True), (4, False), (600, False)]
)
def test_budget_never_returns_partial_token(count: int, complete: bool) -> None:
    db, engine = server([("server", str(n), 1) for n in range(count)])
    try:
        result = observe_revisions(SETTINGS, "counter", 3, lambda _: engine)
        assert result.complete is complete
        assert result.scanned_rows == min(count, 4)
        assert (result.lanes is not None) is complete
        engine.dispose.assert_called_once()
    finally:
        db.close()


def test_sample_is_order_independent_and_detects_reused_lane_increment() -> None:
    db, engine = server([("server", "b", 10), ("server", "a", 1)])
    try:
        first = observe_revisions(SETTINGS, "counter", engine_factory=lambda _: engine)
        assert first.lanes == (("server", "a", 1), ("server", "b", 10))
        db.execute('update "$ingres".counter set revision=11 where session_id="b"')
        assert (
            observe_revisions(SETTINGS, "counter", engine_factory=lambda _: engine)
            != first
        )
    finally:
        db.close()


@pytest.mark.parametrize(
    "rows",
    [
        [("s", "a", 1), ("s", "a", 2)],
        [("s", "a", 0)],
        [("s", "a", -1)],
        [("s", "a", 1.5)],
        [("", "a", 1)],
        [(None, "a", 1)],
        [("s", "x" * 65, 1)],
        [("s", "a", 1), ("s", "b", 0)],
    ],
)
def test_malformed_rows_including_lookahead_fail(rows: list[tuple[Any, ...]]) -> None:
    db, engine = server(rows)
    try:
        with pytest.raises(ProjectError):
            observe_revisions(SETTINGS, "counter", 1, lambda _: engine)
        engine.dispose.assert_called_once()
    finally:
        db.close()


def test_disconnect_disposes_engine() -> None:
    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("disconnected")
    with pytest.raises(RuntimeError, match="disconnected"):
        observe_revisions(SETTINGS, "counter", engine_factory=lambda _: engine)
    engine.dispose.assert_called_once()


def test_complete_sample_spans_fetch_chunks() -> None:
    db, engine = server([("server", str(n), n + 1) for n in range(300)])
    try:
        sample = observe_revisions(SETTINGS, "counter", 300, lambda _: engine)
        assert sample.complete and sample.lanes is not None
        assert len(sample.lanes) == sample.scanned_rows == 300
    finally:
        db.close()


def test_installed_sample_binds_generation_and_rejects_parent_replacement() -> None:
    from uuid import uuid4

    from gorak.revision_observation import observe_installed_revisions

    db, engine = server([])
    parent, generation = str(uuid4()), str(uuid4())
    db.execute('alter table "$ingres".counter rename to gorak_revision_lanes')
    db.execute(
        'create table "$ingres".gorak_tracking_install (schema_version,installation_id,mode)'
    )
    db.execute(
        'create table "$ingres".gorak_revision_install (schema_version,revision_id,parent_installation_id)'
    )
    db.execute(
        'insert into "$ingres".gorak_tracking_install values(2,?,"capture_only")',
        (parent,),
    )
    db.execute(
        'insert into "$ingres".gorak_revision_install values(1,?,?)',
        (generation, parent),
    )

    def execute(statement: Any) -> Any:
        sql = str(statement).strip()
        if sql.startswith("set lockmode"):
            assert "level=mvcc, readlock=shared" in sql
            return []
        match = re.match(r"select first (\d+) ", sql)
        assert match
        return db.execute("select " + sql[match.end() :] + " limit " + match[1])

    engine.connect.return_value.__enter__.return_value.execute.side_effect = execute
    try:
        result = observe_installed_revisions(SETTINGS, engine_factory=lambda _: engine)
        assert result.parent_installation_id == parent
        assert result.revision_id == generation
        assert result.sample.lanes == ()
        db.execute('insert into "$ingres".gorak_revision_lanes values("s","a",1)')
        assert observe_installed_revisions(
            SETTINGS, engine_factory=lambda _: engine
        ).sample.lanes == (("s", "a", 1),)
        db.execute(
            'update "$ingres".gorak_tracking_install set installation_id=?',
            (str(uuid4()),),
        )
        with pytest.raises(ProjectError, match="binding"):
            observe_installed_revisions(SETTINGS, engine_factory=lambda _: engine)
    finally:
        db.close()


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_marker",
        "duplicate_parent",
        "wrong_mode",
        "wrong_version",
        "zero_generation",
        "missing_marker",
    ],
)
def test_installed_binding_rejects_invalid_markers(fault: str) -> None:
    from uuid import uuid4

    from gorak.revision_observation import observe_installed_revisions

    parent = str(uuid4())
    row: list[Any] = [
        1,
        str(uuid4()),
        parent,
        2,
        parent,
        "capture_only",
        1,
        1,
        None,
        None,
        None,
    ]
    changes = {
        "duplicate_marker": (6, 2),
        "duplicate_parent": (7, 2),
        "wrong_mode": (5, "other"),
        "wrong_version": (0, 2),
        "zero_generation": (1, "00000000-0000-0000-0000-000000000000"),
    }
    if fault in changes:
        index, value = changes[fault]
        row[index] = value
    cursor = MagicMock()
    cursor.fetchmany.side_effect = (
        [[], []] if fault == "missing_marker" else [[row], []]
    )
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.side_effect = [
        [],
        [],
        [],
        cursor,
    ]
    with pytest.raises(ProjectError, match="binding"):
        observe_installed_revisions(SETTINGS, engine_factory=lambda _: engine)
    cursor.close.assert_called_once()
    engine.dispose.assert_called_once()

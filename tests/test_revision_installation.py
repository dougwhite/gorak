import sqlite3
from pathlib import Path

import pytest

from gorak.project import ProjectError
from gorak.revision_installation import (
    export_revision_installation_sql,
    revision_installation_sql,
    revision_installation_statements,
)


@pytest.mark.parametrize(
    "versions,allowed",
    [([], False), ([1], False), ([2], True), ([3], False), ([2, 2], False)],
)
def test_guard_rejects_missing_wrong_or_duplicate_parent(
    versions: list[int], allowed: bool
) -> None:
    db = sqlite3.connect(":memory:")
    try:
        db.execute("create table gorak_tracking_install(schema_version,mode)")
        db.executemany(
            "insert into gorak_tracking_install values (?,'capture_only')",
            [(v,) for v in versions],
        )
        statements = revision_installation_statements()
        db.execute(statements[2])
        if allowed:
            db.execute(statements[3])
        else:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statements[3])
    finally:
        db.close()


def test_extension_preserves_parent_schema_and_history() -> None:
    sql = revision_installation_sql()
    assert "after insert on gorak_change_events" in sql
    assert "parent_installation_id" in sql
    assert "update gorak_tracking_install" not in sql
    assert "delete from" not in sql
    assert "create rule gorak_track_" not in sql
    assert "create procedure gorak_record_change" not in sql


def test_export_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "revision.sql"
    export_revision_installation_sql(path)
    original = path.read_bytes()
    with pytest.raises(ProjectError, match="overwrite"):
        export_revision_installation_sql(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "fault",
    [None, "missing_parent", "duplicate_parent", "wrong_parent", "wrong_version"],
)
def test_offline_reset_is_guarded_and_atomic(fault: str | None) -> None:
    from uuid import uuid4

    from gorak.revision_installation import revision_reset_statements

    db = sqlite3.connect(":memory:")
    original, parent = str(uuid4()), str(uuid4())
    db.create_function("uuid_create", 0, lambda: str(uuid4()))
    db.create_function("uuid_to_char", 1, lambda value: value)
    db.executescript("""
    create table gorak_tracking_install(schema_version,installation_id,mode);
    create table gorak_revision_install(schema_version,revision_id,parent_installation_id);
    create table gorak_revision_lanes(server_id,session_id,revision);
    insert into gorak_revision_lanes values('server','session',19);
    """)
    db.execute(
        "insert into gorak_tracking_install values(2,?,'capture_only')", (parent,)
    )
    db.execute("insert into gorak_revision_install values(1,?,?)", (original, parent))
    if fault == "missing_parent":
        db.execute("delete from gorak_tracking_install")
    elif fault == "duplicate_parent":
        db.execute(
            "insert into gorak_tracking_install select * from gorak_tracking_install"
        )
    elif fault == "wrong_parent":
        db.execute("update gorak_revision_install set parent_installation_id='other'")
    elif fault == "wrong_version":
        db.execute("update gorak_revision_install set schema_version=99")
    db.commit()
    try:
        db.execute("begin")
        try:
            for statement in revision_reset_statements()[2:]:
                db.execute(statement)
        except sqlite3.IntegrityError:
            db.rollback()
            assert fault is not None
        else:
            assert fault is None
        identity = db.execute(
            "select revision_id from gorak_revision_install"
        ).fetchone()[0]
        rows = db.execute("select count(*) from gorak_revision_lanes").fetchone()[0]
        assert (identity == original) is (fault is not None)
        assert rows == (1 if fault else 0)
    finally:
        db.close()

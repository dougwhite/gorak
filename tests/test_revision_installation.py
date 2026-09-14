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

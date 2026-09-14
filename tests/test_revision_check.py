import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest

from gorak.database import OdbcSettings
from gorak.installation_check import InstallationCheck
from gorak.revision_check import LAYOUTS, check_revision_installation
from gorak.revision_installation import revision_installation_statements

SETTINGS = OdbcSettings("driver", "host", "port", "source_db", "user", "secret")
PARENT = "12345678-1234-1234-1234-123456789abc"
REVISION = "12345678-1234-1234-1234-123456789abd"


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> Any:
    db = sqlite3.connect(":memory:")
    db.executescript("""
    attach database ':memory:' as "$ingres";
    create table iitables(table_name,table_owner,table_type);
    create table iirules(rule_name,table_name,rule_owner,text_sequence,text_segment);
    create table iiprocedures(procedure_name,procedure_owner,text_sequence,text_segment);
    create table iicolumns(table_name,column_name,column_datatype,column_length,
                          column_nulls,column_sequence,column_scale,table_owner);
    create table "$ingres".gorak_revision_install(schema_version,revision_id,parent_installation_id);
    """)
    db.execute(
        'insert into "$ingres".gorak_revision_install values(1,?,?)', (REVISION, PARENT)
    )
    for table, columns in LAYOUTS.items():
        db.execute("insert into iitables values(?,'$ingres','T')", (table,))
        for index, column in enumerate(columns, 1):
            db.execute(
                "insert into iicolumns values(?,?,?,?,?,?,0,'$ingres')",
                (table, column.name, column.datatype, column.length, "N", index),
            )
    for statement in revision_installation_statements():
        if statement.startswith("create rule"):
            db.execute(
                "insert into iirules values('gorak_revision_capture','gorak_change_events','$ingres',1,?)",
                (statement,),
            )
        if statement.startswith("create procedure"):
            db.execute(
                "insert into iiprocedures values('gorak_bump_revision','$ingres',1,?)",
                (statement,),
            )
    parent = InstallationCheck(
        "capture_only_inventory_present",
        PARENT,
        [],
        schema_version=2,
        definitions_verified=True,
        columns_verified=True,
    )
    monkeypatch.setattr("gorak.revision_check.check_installation", lambda *_: parent)
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    queried = False

    def rollback() -> None:
        nonlocal queried
        queried = False

    connection.rollback.side_effect = rollback

    def execute(statement: Any) -> Any:
        nonlocal queried
        sql = str(statement)
        if sql.startswith("set lockmode"):
            assert not queried, "LOCKMODE must precede transaction reads"
            assert "shared" in sql
            return []
        queried = True
        if "select first 2" in sql:
            sql = sql.replace("select first 2", "select") + " limit 2"
        return db.execute(sql)

    engine.connect.return_value.__enter__.return_value.execute.side_effect = execute
    yield db, engine, parent
    db.close()


def test_healthy_structure_is_not_fast_path_certification(catalog: Any) -> None:
    _, engine, _ = catalog
    report = check_revision_installation(SETTINGS, lambda _: engine)
    assert report.status == "revision_structure_verified"
    assert report.revision_id == REVISION
    assert report.columns_verified and report.definitions_verified
    assert not report.incremental_ready
    engine.dispose.assert_called_once()


@pytest.mark.parametrize(
    "mutation",
    [
        "delete from iitables where table_name='gorak_revision_lanes'",
        "update iitables set table_owner='developer'",
        "update iirules set rule_owner='developer'",
        "update iirules set table_name='different_events'",
        "update iirules set text_segment=replace(text_segment,'after insert','after delete')",
        "update iiprocedures set text_segment=replace(text_segment,'revision+1','revision+0')",
        "update iiprocedures set text_sequence=2",
        "delete from iiprocedures",
        "update iicolumns set column_length=4 where column_name='revision'",
        "update iicolumns set column_nulls='Y' where column_name='server_id'",
        "update iicolumns set column_sequence=9 where column_name='session_id'",
        "delete from iicolumns",
        'delete from "$ingres".gorak_revision_install',
        'insert into "$ingres".gorak_revision_install select * from "$ingres".gorak_revision_install',
        'update "$ingres".gorak_revision_install set schema_version=2',
        "update \"$ingres\".gorak_revision_install set revision_id='00000000-0000-0000-0000-000000000000'",
        "update \"$ingres\".gorak_revision_install set parent_installation_id='invalid'",
        f"update \"$ingres\".gorak_revision_install set parent_installation_id='{REVISION}'",
    ],
)
def test_damaged_extension_never_passes(catalog: Any, mutation: str) -> None:
    db, engine, _ = catalog
    db.execute(mutation)
    report = check_revision_installation(SETTINGS, lambda _: engine)
    assert report.status == "incomplete" and report.issues
    assert not report.incremental_ready


def test_parent_damage_prevents_success(catalog: Any) -> None:
    _, engine, parent = catalog
    parent.issues.append("Missing capture rule")
    report = check_revision_installation(SETTINGS, lambda _: engine)
    assert report.issues == ["Parent tracking: Missing capture rule"]


def test_connection_failure_disposes_engine(catalog: Any) -> None:
    _, engine, _ = catalog
    engine.connect.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        check_revision_installation(SETTINGS, lambda _: engine)
    engine.dispose.assert_called_once()

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from gorak.database import OdbcSettings
from gorak.installation import installation_statements
from gorak.installation_check import (
    CATALOG_QUERIES,
    EXPECTED_RULES,
    EXPECTED_TABLES,
    check_installation,
)
from gorak.installation_definitions import (
    PROCEDURE_DEFINITION_SQL,
    RULE_DEFINITIONS_SQL,
)
from gorak.installation_schema import COLUMN_SQL, expected_columns


def fixture() -> tuple[MagicMock, dict[str, list[tuple[Any, ...]]]]:
    rows: dict[str, list[tuple[Any, ...]]] = {
        CATALOG_QUERIES["tables"]: [(name + " ",) for name in EXPECTED_TABLES],
        CATALOG_QUERIES["rules"]: list(EXPECTED_RULES.items()),
        CATALOG_QUERIES["procedures"]: [("gorak_record_change",)],
        CATALOG_QUERIES["sequences"]: [("gorak_change_seq",)],
        'select schema_version, installation_id, mode from "$ingres".gorak_tracking_install': [
            (1, str(uuid4()), "capture_only")
        ],
    }
    rows[COLUMN_SQL] = [
        (
            table,
            column.name,
            column.datatype,
            column.length,
            "Y" if column.nullable else "N",
            i,
            0,
        )
        for table, columns in expected_columns().items()
        for i, column in enumerate(columns, 1)
    ]
    statements = installation_statements()
    rows[RULE_DEFINITIONS_SQL] = [
        (s.split()[2], 1, s) for s in statements if s.startswith("create rule ")
    ]
    rows[PROCEDURE_DEFINITION_SQL] = [
        (1, s) for s in statements if s.startswith("create procedure ")
    ]
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.side_effect = (
        lambda query: rows.get(str(query), [])
    )
    return engine, rows


def run(engine: MagicMock) -> Any:
    settings = OdbcSettings("driver", "host", "port", "source_db", "user", "secret")
    return check_installation(settings, engine_factory=lambda _: engine)


def test_complete_inventory_does_not_claim_incremental_readiness() -> None:
    engine, _ = fixture()
    report = run(engine)
    assert not report.issues
    assert report.status == "capture_only_inventory_present"
    assert report.installation_id
    assert report.incremental_ready is False
    assert report.definitions_verified is True
    assert report.columns_verified is True
    engine.dispose.assert_called_once()


def test_missing_tables_does_not_query_marker() -> None:
    engine, rows = fixture()
    rows[CATALOG_QUERIES["tables"]] = []
    assert len(run(engine).issues) == 2
    queries = engine.connect.return_value.__enter__.return_value.execute.call_args_list
    assert not any('from "$ingres"' in str(call.args[0]) for call in queries)


def test_wrong_rule_target_and_missing_sequence_detected() -> None:
    engine, rows = fixture()
    rows[CATALOG_QUERIES["rules"]][0] = ("gorak_track_0_i", "wrong_table")
    rows[CATALOG_QUERIES["sequences"]] = []
    issues = run(engine).issues
    assert len(issues) == 2
    assert any("wrong-target" in issue for issue in issues)


@pytest.mark.parametrize(
    "records",
    [
        [],
        [(1, str(uuid4()), "capture_only")] * 2,
        [(3, str(uuid4()), "capture_only")],
        [(1, "bad-uuid", "capture_only")],
        [(1, str(uuid4()), "unknown")],
    ],
)
def test_invalid_marker_fails_check(records: list[tuple[Any, ...]]) -> None:
    engine, rows = fixture()
    marker = next(key for key in rows if "schema_version" in key)
    rows[marker] = records
    assert run(engine).issues


def test_permission_error_is_not_reported_as_success_and_disposes() -> None:
    engine, _ = fixture()
    engine.connect.return_value.__enter__.return_value.execute.side_effect = (
        RuntimeError("permission denied")
    )
    with pytest.raises(RuntimeError, match="permission denied"):
        run(engine)
    engine.dispose.assert_called_once()


def test_v2_requires_ack_table_and_reports_schema_version() -> None:
    engine, rows = fixture()
    marker = next(key for key in rows if "schema_version" in key)
    rows[marker] = [(2, str(uuid4()), "capture_only")]
    assert "Missing owner tables: gorak_journal_acks" in run(engine).issues
    rows[CATALOG_QUERIES["tables"]].append(("gorak_journal_acks",))
    report = run(engine)
    assert not report.issues
    assert report.schema_version == 2


def test_inventory_with_modified_hook_is_incomplete() -> None:
    engine, rows = fixture()
    name, sequence, sql = rows[RULE_DEFINITIONS_SQL][0]
    rows[RULE_DEFINITIONS_SQL][0] = (
        name,
        sequence,
        sql.replace("p_action='i'", "p_action='x'"),
    )
    report = run(engine)
    assert report.status == "incomplete"
    assert report.definitions_verified is False
    assert any("modified capture rule definition" in issue for issue in report.issues)


def test_missing_catalog_definition_fails_closed() -> None:
    engine, rows = fixture()
    rows[PROCEDURE_DEFINITION_SQL] = []
    report = run(engine)
    assert report.status == "incomplete"
    assert report.definitions_verified is False
    assert any("procedure definition" in issue for issue in report.issues)


def test_modified_column_layout_makes_inventory_incomplete() -> None:
    engine, rows = fixture()
    rows[COLUMN_SQL] = [row for row in rows[COLUMN_SQL] if row[1] != "source_table"]
    report = run(engine)
    assert report.status == "incomplete"
    assert report.definitions_verified is True
    assert report.columns_verified is False
    assert any("column layout: gorak_change_events" in issue for issue in report.issues)

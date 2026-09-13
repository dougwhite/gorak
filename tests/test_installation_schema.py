from typing import Any
from unittest.mock import MagicMock

import pytest

from gorak.installation_schema import column_issues, expected_columns


def fixture() -> tuple[MagicMock, list[list[Any]]]:
    rows = [
        [
            table + " ",
            column.name + " ",
            column.datatype.upper() + " ",
            column.length,
            "Y" if column.nullable else "N",
            i,
            0,
        ]
        for table, columns in expected_columns().items()
        for i, column in enumerate(columns, 1)
    ]
    connection = MagicMock()
    connection.execute.return_value = rows
    return connection, rows


def test_catalog_matches_generated_layout() -> None:
    connection, rows = fixture()
    rows.reverse()
    assert not column_issues(connection, set(expected_columns()))


@pytest.mark.parametrize(
    "index,value",
    [
        (1, "wrong_name"),
        (2, "VARCHAR"),
        (3, 4),
        (4, "Y"),
        (5, 2),
        (6, 1),
    ],
)
def test_event_identity_column_changes_are_detected(index: int, value: Any) -> None:
    connection, rows = fixture()
    row = next(
        r
        for r in rows
        if r[0].strip() == "gorak_change_events" and r[1].strip() == "event_id"
    )
    row[index] = value
    issues = column_issues(connection, set(expected_columns()))
    assert len(issues) == 1
    assert "gorak_change_events" in issues[0]


def test_missing_and_extra_columns_are_detected() -> None:
    connection, rows = fixture()
    rows.pop()
    rows.append(["gorak_tracking_install", "extra", "integer", 4, "Y", 4, 0])
    assert len(column_issues(connection, set(expected_columns()))) == 2


def test_missing_catalog_rows_fail_closed() -> None:
    connection = MagicMock()
    connection.execute.return_value = []
    assert len(column_issues(connection, set(expected_columns()))) == 3


def test_unknown_nullability_fails_closed() -> None:
    connection, rows = fixture()
    rows[0][4] = "?"
    assert column_issues(connection, set(expected_columns())) == [
        "Invalid tracking column catalog metadata"
    ]


def test_missing_inventory_does_not_query_catalog() -> None:
    connection = MagicMock()
    assert column_issues(connection, set()) == []
    connection.execute.assert_not_called()

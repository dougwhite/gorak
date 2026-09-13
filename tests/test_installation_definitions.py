from typing import Any
from unittest.mock import MagicMock

from gorak.installation import installation_statements
from gorak.installation_definitions import (
    PROCEDURE_DEFINITION_SQL,
    RULE_DEFINITIONS_SQL,
    assemble,
    canonical_sql,
    definition_issues,
)


def test_catalog_owner_qualification_whitespace_and_keyword_case() -> None:
    assert canonical_sql(
        "execute procedure gorak_record_change(p_action='u')"
    ) == canonical_sql(
        "EXECUTE  PROCEDURE \"$ingres\". gorak_record_change ( p_action = 'u' );"
    )


def test_literals_and_foreign_owner_are_not_normalized_away() -> None:
    assert canonical_sql("select 'two words'") != canonical_sql("select 'twowords'")
    assert canonical_sql("select 'U'") != canonical_sql("select 'u'")
    assert canonical_sql('select * from "$other".gorak_change_events') != canonical_sql(
        'select * from "$ingres".gorak_change_events'
    )
    assert canonical_sql('select "One", "Two"') != canonical_sql('select "one", "two"')


def test_segments_join_without_losing_token_boundaries() -> None:
    assert assemble([(2, "tion"), (1, "ac")]) == "action"
    assert assemble([(1, "a"), (3, "b")]) is None
    assert assemble([(1, "a"), (1, "b")]) is None


def test_modified_rule_and_procedure_are_reported() -> None:
    statements = installation_statements()
    rule = next(s for s in statements if s.startswith("create rule "))
    procedure = next(s for s in statements if s.startswith("create procedure "))
    name = rule.split()[2]
    connection = MagicMock()

    def execute(query: Any) -> list[tuple[Any, ...]]:
        if str(query) == RULE_DEFINITIONS_SQL:
            return [(name, 1, rule.replace("p_action='i'", "p_action='d'"))]
        return [(1, procedure.replace(":p_action", "'x'"))]

    connection.execute.side_effect = execute
    issues = definition_issues(connection, {name}, True)
    assert len(issues) == 2


def test_expected_catalog_segments_all_match() -> None:
    statements = installation_statements()
    rules = [s for s in statements if s.startswith("create rule ")]
    procedure = next(s for s in statements if s.startswith("create procedure "))
    rows: list[tuple[str, int, str]] = []
    for rule in rules:
        rule = rule.replace(
            "execute procedure gorak_record_change",
            'execute procedure "$ingres". gorak_record_change',
        )
        rows.extend(
            (rule.split()[2], i // 120 + 1, rule[i : i + 120])
            for i in range(0, len(rule), 120)
        )
    connection = MagicMock()

    def execute(query: Any) -> list[tuple[Any, ...]]:
        if str(query) == RULE_DEFINITIONS_SQL:
            return rows
        if str(query) == PROCEDURE_DEFINITION_SQL:
            return [(1, procedure)]
        return []

    connection.execute.side_effect = execute
    assert definition_issues(connection, {s.split()[2] for s in rules}, True) == []

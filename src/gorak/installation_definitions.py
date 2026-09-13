"""Compare capture SQL definitions without normalizing away literal changes."""

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import text

from .installation import installation_statements

RULE_DEFINITIONS_SQL = """
select rule_name, text_sequence, text_segment from iirules
where rule_owner = '$ingres' and rule_name like 'gorak_track_%'
"""
PROCEDURE_DEFINITION_SQL = """
select text_sequence, text_segment from iiprocedures
where procedure_owner = '$ingres' and procedure_name = 'gorak_record_change'
"""
TOKEN = re.compile(
    r"""'(?:''|[^'])*'|"(?:""|[^"])*"|[$A-Za-z_][$A-Za-z_0-9]*|[0-9]+|[^\s]"""
)


def canonical_sql(sql: str) -> tuple[str, ...]:
    tokens = TOKEN.findall(sql)
    result: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        # Ingres qualifies references with their resolved owner in stored text.
        if (
            token in {'"$ingres"', "$ingres"}
            and index + 1 < len(tokens)
            and tokens[index + 1] == "."
        ):
            index += 2
            continue
        result.append(token if token.startswith(("'", '"')) else token.lower())
        index += 1
    if result and result[-1] == ";":
        result.pop()
    return tuple(result)


def assemble(segments: list[tuple[int, str]]) -> str | None:
    ordered = sorted(segments)
    if [number for number, _ in ordered] != list(range(1, len(ordered) + 1)):
        return None
    # Catalog segments can split in the middle of a token; do not strip or join with spaces.
    return "".join(value for _, value in ordered) if ordered else None


def definition_issues(
    connection: Any, present_rules: set[str], procedure_present: bool
) -> list[str]:
    expected = {
        statement.split()[2]: statement
        for statement in installation_statements()
        if statement.startswith("create rule ")
    }
    issues = []
    if present_rules:
        segments: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for row in connection.execute(text(RULE_DEFINITIONS_SQL)):
            segments[str(row[0]).strip()].append((int(row[1]), str(row[2])))
        for name in sorted(present_rules & expected.keys()):
            actual = assemble(segments[name])
            if actual is None or canonical_sql(actual) != canonical_sql(expected[name]):
                issues.append(f"Missing or modified capture rule definition: {name}")
    if procedure_present:
        actual = assemble(
            [
                (int(row[0]), str(row[1]))
                for row in connection.execute(text(PROCEDURE_DEFINITION_SQL))
            ]
        )
        expected_procedure = next(
            s for s in installation_statements() if s.startswith("create procedure ")
        )
        if actual is None or canonical_sql(actual) != canonical_sql(expected_procedure):
            issues.append(
                "Missing or modified capture procedure definition: gorak_record_change"
            )
    return issues

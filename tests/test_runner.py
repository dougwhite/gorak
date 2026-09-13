from pathlib import Path

import pytest

from gorak.project import ProjectError
from gorak.runner import report_summary
from gorak.runner import test_applications as load_tests


def test_report_captures_assertions() -> None:
    result = report_summary(
        '<testsuites><testsuite tests="2" failures="1" errors="0" skipped="0"><testcase name="setup"/><testcase classname="Example" name="check"><failure message="expected 1 actual 2 (line 10)"/></testcase></testsuite></testsuites>'
    )
    assert result.tests == 2
    assert result.failures == 1
    assert result.messages == ["Example.check: expected 1 actual 2 (line 10)"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "<testsuites/>",
        "<invalid/>",
        '<testsuite tests="2"><testcase name="one"/></testsuite>',
    ],
)
def test_missing_or_incomplete_report_is_error(text: str) -> None:
    with pytest.raises(ProjectError):
        report_summary(text)


def test_config_supports_multiple_suites(tmp_path: Path) -> None:
    (tmp_path / "gorak.json").write_text(
        '{"tests":[{"application":"tests_a","timeout_seconds":20},"tests_b"]}'
    )
    assert [x.application for x in load_tests(tmp_path)] == ["tests_a", "tests_b"]

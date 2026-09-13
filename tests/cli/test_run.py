from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak.connection import OpenRoadConnection
from gorak.run_backend import RunResult
from gorak.runner import TestApplication as ApplicationRun


@pytest.mark.parametrize(
    "report,code,expected",
    [
        ('<testsuite tests="1"><testcase name="works"/></testsuite>', 0, 0),
        (
            '<testsuite tests="1" failures="1"><testcase name="fails"><failure message="bad"/></testcase></testsuite>',
            0,
            1,
        ),
        ("", 0, 1),
        ('<testsuite tests="1"><testcase name="works"/></testsuite>', 1, 1),
    ],
)
def test_test_command_reports_results(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    report: str,
    code: int,
    expected: int,
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"example","tests":["test_app"]}')
    monkeypatch.chdir(tmp_path)

    def run(
        connection: OpenRoadConnection,
        suite: ApplicationRun,
        env: dict[str, str],
        artifacts: Path,
        testing: bool,
    ) -> RunResult:
        assert suite.application == "test_app"
        assert testing
        return RunResult(code, False, "trace", report, "trace.log")

    monkeypatch.setattr(cli, "execute_application", run)
    with pytest.raises(SystemExit) as ex:
        cli.main(
            ["test", "--backend", "local", "--vnode", "node", "--database", "source"]
        )
    assert ex.value.code == expected
    assert "Artifacts:" in capsys.readouterr().out


@pytest.mark.parametrize("skipped,expected", [(True, 0), (False, 1)])
def test_framework_exit_two_requires_reported_skips(
    tmp_path: Path, monkeypatch: MonkeyPatch, skipped: bool, expected: int
) -> None:
    monkeypatch.chdir(tmp_path)
    report = (
        '<testsuite tests="1"><testcase name="sample">'
        + ("<skipped/>" if skipped else "")
        + "</testcase></testsuite>"
    )
    monkeypatch.setattr(
        cli,
        "execute_application",
        lambda *args: RunResult(2, False, "", report, "trace"),
    )
    with pytest.raises(SystemExit) as ex:
        cli.main(
            [
                "test",
                "--app",
                "tests",
                "--backend",
                "local",
                "--vnode",
                "node",
                "--database",
                "source",
            ]
        )
    assert ex.value.code == expected

import json
import subprocess
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from gorak import run_backend
from gorak.connection import OpenRoadConnection
from gorak.project import ProjectError
from gorak.remote import RemoteHost
from gorak.runner import TestApplication as ApplicationRun


def test_remote_runner_transfers_config_without_shell_interpolation(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    requests: list[dict[str, object]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[0] == "scp":
            requests.append(json.loads(Path(command[1]).read_text()))
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "exit_code": 1,
                    "timed_out": False,
                    "trace": "failed",
                    "report": "<testsuites/>",
                    "trace_path": "C:\\temp\\test.log",
                    "output": "",
                }
            ),
            "",
        )

    monkeypatch.setattr(subprocess, "run", run)
    result = run_backend.execute_application(
        OpenRoadConnection(
            "remote", "node", "source", RemoteHost("dev", "host", r"C:\Gorak Tools")
        ),
        ApplicationRun("tests"),
        {
            "GORAK_TRACE_DIR": r"C:\Trace Logs",
            "GORAK_RUN_ENV_API_TOKEN": "secret & value",
        },
        tmp_path / "artifacts",
        True,
    )
    assert requests[0]["environment"] == {"API_TOKEN": "secret & value"}
    assert "secret" not in str(calls)
    assert result.exit_code == 1
    assert (tmp_path / "artifacts/results.xml").read_text() == "<testsuites/>"


def test_local_run_uses_saved_runtime_and_collects_results(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    # A real short subprocess exercises output capture and environment inheritance.
    fake = tmp_path / "w4gldev"
    fake.write_text(
        '#!/usr/bin/python3\nimport os,sys\nfrom pathlib import Path\nassert not any(a.startswith("-d") for a in sys.argv)\nPath(os.environ["OR_UNITTEST_STATSFILE_XML"]).write_text("<testsuites/>")\nprint("executed")\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin")
    result = run_backend.execute_application(
        OpenRoadConnection("local", "node", "source", None),
        ApplicationRun("tests"),
        {"GORAK_TRACE_MODE": "temp"},
        tmp_path / "artifacts",
        True,
    )
    assert result.exit_code == 0
    assert result.output.strip() == "executed"
    assert result.report == "<testsuites/>"
    assert not Path(result.trace_path).parent.exists()


def test_local_timeout_is_reported(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    fake = tmp_path / "w4gldev"
    fake.write_text("#!/usr/bin/python3\nimport time\ntime.sleep(10)\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin")
    result = run_backend.execute_application(
        OpenRoadConnection("local", "node", "source", None),
        ApplicationRun("tests", timeout_seconds=1),
        {},
        tmp_path / "artifacts",
        True,
    )
    assert result.timed_out
    assert result.exit_code == 124


def test_invalid_mode_does_not_launch(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="TRACE_MODE"):
        run_backend.execute_application(
            OpenRoadConnection("local", "node", "source", None),
            ApplicationRun("tests"),
            {"GORAK_TRACE_MODE": "invalid"},
            tmp_path / "artifacts",
            True,
        )

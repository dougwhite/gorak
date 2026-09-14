import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from gorak import revision_route as route
from gorak.connection import OpenRoadConnection
from gorak.errors import ProjectError
from gorak.remote import RemoteHost

GENERATION = "12345678-1234-1234-1234-123456789abc"


def test_local_route_uses_selected_installation_and_rejects_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = OpenRoadConnection(
        "local", "node", "source", None, revision_generation=GENERATION
    )
    monkeypatch.setenv("II_SYSTEM", str(tmp_path))
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, f"|revision_id|\n|{GENERATION}|", ""
        )
    )
    monkeypatch.setattr("gorak.revision_route.subprocess.run", run)
    route.validate_source_route(connection)
    assert run.call_args.args[0][0] == str(tmp_path / "ingres/bin/sql")
    assert '"$ingres".gorak_revision_install' in run.call_args.kwargs["input"]
    run.return_value.stdout = "|another-generation|"
    with pytest.raises(ProjectError, match="does not match"):
        route.validate_source_route(connection)


@pytest.mark.parametrize(
    "output",
    [
        "",
        "|wrong|",
        f"|{GENERATION}|\n|{GENERATION}|",
        f"|{GENERATION}|\nE_TEST failure",
    ],
)
def test_remote_route_fails_closed(
    output: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = OpenRoadConnection(
        "remote",
        "node",
        "source",
        RemoteHost("user", "host", r"C:\gorak"),
        revision_generation=GENERATION,
    )
    monkeypatch.setattr(route, "verify_remote_helpers", lambda *_: None)
    commands: list[Any] = []

    def run(command: Any, **kwargs: Any) -> Any:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr("gorak.revision_route.subprocess.run", run)
    with pytest.raises(ProjectError, match="does not match"):
        route.validate_source_route(connection)
    assert commands[0][0] == "ssh"
    assert "get-revision-generation.bat node source" in commands[0][-1]
    route.validate_source_route(replace(connection, revision_generation=None))
    assert len(commands) == 1


def test_export_route_mismatch_prevents_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import export

    connection = OpenRoadConnection(
        "local", "node", "source", None, revision_generation=GENERATION
    )

    def reject(_: Any) -> None:
        raise ProjectError("route mismatch")

    monkeypatch.setattr(export, "validate_source_route", reject)
    run = Mock()
    monkeypatch.setattr("gorak.export.local.backup_application", run)
    with pytest.raises(ProjectError, match="route mismatch"):
        export.backup_application_xml(connection, "app", tmp_path / "app.xml")
    run.assert_not_called()


@pytest.mark.parametrize(
    "variable", ["II_SYSTEM", "ii_config", "II_INSTALLATION", "II_GCN_PORT"]
)
def test_managed_run_rejects_routing_override_before_connecting(
    variable: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.run_backend import execute_application
    from gorak.runner import TestApplication

    connection = OpenRoadConnection(
        "local", "node", "source", None, revision_generation=GENERATION
    )
    validate = Mock()
    monkeypatch.setattr("gorak.revision_check.validate_revision_target", validate)
    with pytest.raises(ProjectError, match="cannot override"):
        execute_application(
            connection,
            TestApplication("app"),
            {"GORAK_RUN_ENV_" + variable: "another"},
            tmp_path / "run",
            False,
        )
    validate.assert_not_called()

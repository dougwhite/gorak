import base64
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gorak import install_backend
from gorak.connection import OpenRoadConnection
from gorak.database import OdbcSettings
from gorak.install_backend import install_command, install_tracking
from gorak.installation_check import InstallationCheck
from gorak.project import ProjectError
from gorak.remote import RemoteHost


@pytest.fixture(autouse=True)
def no_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install_backend, "run_subprocess", lambda _: "")


def connection() -> OpenRoadConnection:
    return OpenRoadConnection(
        backend="remote",
        vnode="source-node",
        database="source_db",
        remote_host=RemoteHost("developer", "build-host", r"C:\gorak"),
        sql_backend="odbc",
        odbc_settings=OdbcSettings(
            "driver", "host", "port", "source_db", "user", "secret"
        ),
    )


def test_remote_uses_ssh_even_with_odbc_configured() -> None:
    command = install_command(connection(), r"C:\gorak\install.sql")
    assert command[:3] == ["ssh", "-T", "developer@build-host"]
    script = base64.b64decode(command[-1].split()[-1]).decode("utf-16-le")
    assert "'-u$ingres' 'source-node::source_db'" in script
    assert "II_TM_EXIT_ON_ERROR = 'rollback'" in script


def test_local_uses_argument_vector() -> None:
    from dataclasses import replace

    assert install_command(replace(connection(), backend="local")) == [
        "sql",
        "-u$ingres",
        "source-node::source_db",
    ]


def test_success_saves_script_log_and_checks_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = InstallationCheck(
        "capture_only_inventory_present", "id", [], schema_version=2
    )
    checks = MagicMock(
        side_effect=[
            InstallationCheck(
                "incomplete", None, ["missing"], tracking_objects_present=False
            ),
            ready,
        ]
    )
    run = MagicMock(return_value=subprocess.CompletedProcess([], 0, "done", ""))
    monkeypatch.setattr(install_backend, "check_installation", checks)
    monkeypatch.setattr(subprocess, "run", run)
    assert install_tracking(connection(), tmp_path) == ready
    assert checks.call_count == 2
    sql = next(tmp_path.glob("*/install.sql")).read_text()
    assert 'grant select on gorak_tracking_install to "user"' in sql
    assert 'grant select on gorak_change_events to "user"' in sql
    assert sql.index("grant select") < sql.index("commit;")
    assert "grant all" not in sql.lower()
    assert list(tmp_path.glob("*/install.log"))
    assert run.call_args.kwargs["env"]["II_TM_EXIT_ON_ERROR"] == "rollback"


@pytest.mark.parametrize("code,output", [(1, "failure"), (0, "E_US1234 SQL failure")])
def test_sql_failure_does_not_report_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, output: str
) -> None:
    monkeypatch.setattr(
        install_backend,
        "check_installation",
        lambda _: InstallationCheck(
            "incomplete", None, ["missing"], tracking_objects_present=False
        ),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], code, output, ""),
    )
    with pytest.raises(ProjectError, match="SQL failed"):
        install_tracking(connection(), tmp_path)


def test_partial_installation_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        install_backend,
        "check_installation",
        lambda _: InstallationCheck("incomplete", None, ["wrong rule"]),
    )
    with pytest.raises(ProjectError, match="partial"):
        install_tracking(connection(), tmp_path)
    assert not list(tmp_path.iterdir())


def test_existing_installation_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = InstallationCheck(
        "capture_only_inventory_present", "id", [], schema_version=2
    )
    monkeypatch.setattr(install_backend, "check_installation", lambda _: ready)
    assert install_tracking(connection(), tmp_path) == ready
    assert not list(tmp_path.iterdir())


def test_verification_failure_explains_installation_may_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        install_backend,
        "check_installation",
        MagicMock(
            side_effect=[
                InstallationCheck(
                    "incomplete", None, ["missing"], tracking_objects_present=False
                ),
                RuntimeError("read permission"),
            ]
        ),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, "done", ""),
    )
    with pytest.raises(ProjectError, match="installation may exist"):
        install_tracking(connection(), tmp_path)


def test_mismatched_database_rejected_before_connection(tmp_path: Path) -> None:
    from dataclasses import replace

    with pytest.raises(ProjectError, match="targets differ"):
        install_tracking(replace(connection(), database="different_db"), tmp_path)


def test_v1_requires_explicit_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = InstallationCheck(
        "capture_only_inventory_present", "id", [], schema_version=1
    )
    monkeypatch.setattr(install_backend, "check_installation", lambda _: ready)
    with pytest.raises(ProjectError, match="--upgrade"):
        install_tracking(connection(), tmp_path)
    assert not list(tmp_path.iterdir())


def test_upgrade_applies_migration_and_ack_grants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        install_backend,
        "check_installation",
        MagicMock(
            side_effect=[
                InstallationCheck(
                    "capture_only_inventory_present", "id", [], schema_version=1
                ),
                InstallationCheck(
                    "capture_only_inventory_present", "id", [], schema_version=2
                ),
            ]
        ),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, "done", ""),
    )
    assert install_tracking(connection(), tmp_path, upgrade=True).schema_version == 2
    sql = next(tmp_path.glob("*/install.sql")).read_text()
    assert 'grant select, insert on gorak_journal_acks to "user"' in sql
    assert "update gorak_tracking_install" in sql
    assert "create rule gorak_track_" not in sql


def test_upgrade_refuses_missing_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        install_backend,
        "check_installation",
        lambda _: InstallationCheck(
            "incomplete", None, ["missing"], tracking_objects_present=False
        ),
    )
    with pytest.raises(ProjectError, match="complete version 1"):
        install_tracking(connection(), tmp_path, upgrade=True)

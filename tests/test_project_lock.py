import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from gorak import cli
from gorak.project import ProjectError
from gorak.project_lock import project_lock


def test_lock_excludes_another_operation_and_releases_after_failure(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="failed"):
        with project_lock(tmp_path, "first"):
            record = json.loads((tmp_path / ".openroad/mutation.lock").read_text())
            assert record["operation"] == "first"
            with pytest.raises(ProjectError, match="Another Gorak operation"):
                with project_lock(tmp_path, "second"):
                    pytest.fail("Second operation acquired the lock")
            raise RuntimeError("failed")
    with project_lock(tmp_path, "third"):
        pass
    assert not (tmp_path / ".openroad/mutation.lock").exists()


@pytest.mark.parametrize(
    "marker", ["pull.lock", "pull-pending.json", "push-pending.json"]
)
def test_unfinished_pull_blocks_mutations(tmp_path: Path, marker: str) -> None:
    directory = tmp_path / ".openroad"
    directory.mkdir()
    (directory / marker).write_text("retained recovery marker")
    with pytest.raises(ProjectError, match="Unfinished source operation"):
        with project_lock(tmp_path, "export"):
            pytest.fail("Recovery marker was ignored")
    assert (directory / marker).exists()
    assert not (directory / "mutation.lock").exists()


@pytest.mark.parametrize(
    "name",
    [
        "new_command",
        "encode_command",
        "config_remote_command",
        "export_component_command",
        "app_export_command",
        "component_import_command",
        "defaults_flatten_command",
        "sync_command",
    ],
)
def test_cli_mutations_stop_before_backend_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    monkeypatch.chdir(tmp_path)
    with project_lock(tmp_path, "active"):
        with pytest.raises(ProjectError, match="Another Gorak operation"):
            getattr(cli, name)(argparse.Namespace())


def test_proven_dead_local_lock_is_reclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import psutil

    directory = tmp_path / ".openroad"
    directory.mkdir()
    lock = directory / "mutation.lock"
    lock.write_text(json.dumps({"pid": 12345678, "operation": "interrupted"}))
    real = psutil.Process

    def process(pid: int | None = None) -> Any:
        if pid == 12345678:
            raise psutil.NoSuchProcess(pid)
        return real(pid)

    monkeypatch.setattr(psutil, "Process", process)
    with project_lock(tmp_path, "retry"):
        assert json.loads(lock.read_text())["operation"] == "retry"
    assert not lock.exists()


def test_remote_lock_owner_is_not_reclaimed(tmp_path: Path) -> None:
    directory = tmp_path / ".openroad"
    directory.mkdir()
    lock = directory / "mutation.lock"
    lock.write_text(json.dumps({"pid": 12345678, "host": "some-other-host"}))
    with pytest.raises(ProjectError, match="may be active"):
        with project_lock(tmp_path, "retry"):
            pytest.fail("Acquired remote owner lock")
    assert lock.exists()

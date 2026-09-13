from pathlib import Path

import pytest

from gorak import sync_guard
from gorak.connection import OpenRoadConnection
from gorak.project import ProjectError
from gorak.sync_plan import Change


def connection(database: str = "source") -> OpenRoadConnection:
    return OpenRoadConnection("local", "node", database, None)


def test_rebinding_to_another_target_is_rejected(tmp_path: Path) -> None:
    sync_guard.save_binding(connection(), tmp_path)
    with pytest.raises(ProjectError, match="different configured target"):
        sync_guard.binding_status(connection("other"), tmp_path)


@pytest.mark.parametrize(
    "action,disk,database,push",
    [
        ("conflict", "modified", "modified", True),
        ("push", "modified", "unchanged", False),
        ("pull", "unchanged", "modified", True),
        ("pull", "unchanged", "deleted", False),
        ("push", "deleted", "unchanged", True),
    ],
)
def test_unsafe_plans_block_before_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    disk: str,
    database: str,
    push: bool,
) -> None:
    from typing import cast

    from gorak.sync_plan import Action

    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    monkeypatch.setattr(
        sync_guard,
        "plan_project",
        lambda c, r: [Change("example/proc", cast(Action, action), disk, database)],
    )
    with pytest.raises(ProjectError, match="before writes"):
        sync_guard.guard_sync(connection(), tmp_path, push=push)
    assert not (tmp_path / ".openroad/sync-target.json").exists()


def test_bind_requires_database_to_match_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    monkeypatch.setattr(
        sync_guard,
        "plan_project",
        lambda c, r: [Change("example/proc", "pull", "unchanged", "modified")],
    )
    with pytest.raises(ProjectError, match="Cannot bind"):
        sync_guard.guard_sync(connection(), tmp_path, push=False, bind=True)
    assert not (tmp_path / ".openroad/sync-target.json").exists()


def test_dry_run_never_creates_binding(tmp_path: Path) -> None:
    sync_guard.guard_sync(connection(), tmp_path, push=True, dry_run=True)
    assert not (tmp_path / ".openroad").exists()

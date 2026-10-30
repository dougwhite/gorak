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


def test_guard_forwards_optional_planning_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    captures: list[Path | None] = []

    def planning(
        c: OpenRoadConnection, root: Path, *, capture_dir: Path | None = None
    ) -> list[Change]:
        captures.append(capture_dir)
        return []

    monkeypatch.setattr(sync_guard, "plan_project", planning)
    destination = tmp_path / "capture"
    sync_guard.guard_sync(
        connection(), tmp_path, push=False, dry_run=True, capture_dir=destination
    )
    assert captures == [destination]


@pytest.mark.parametrize("dry_run", [False, True])
def test_empty_database_defers_reconstruction_only_to_locked_creation_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    from gorak import export

    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    monkeypatch.setattr(export, "read_applications", lambda c: [])
    monkeypatch.setattr(
        sync_guard,
        "plan_project",
        lambda *a, **k: pytest.fail("Duplicate reconstruction"),
    )
    assert (
        sync_guard.guard_sync(
            connection(),
            tmp_path,
            push=True,
            lock_held=True,
            creation_preflight=True,
            dry_run=dry_run,
        )
        == []
    )
    assert (tmp_path / ".openroad/sync-target.json").exists() != dry_run


@pytest.mark.parametrize("reason", ["database", "tracked", "unlocked"])
def test_creation_shortcut_does_not_bypass_existing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    from gorak import export
    from gorak.domain import Application

    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    if reason == "tracked":
        cache = tmp_path / ".openroad"
        cache.mkdir()
        (cache / "tracked-applications.json").write_text("[]")
    monkeypatch.setattr(
        export,
        "read_applications",
        lambda c: [Application("other", "", "")] if reason == "database" else [],
    )
    planned = []

    def planning(*args: object, **kwargs: object) -> list[Change]:
        planned.append(True)
        return []

    monkeypatch.setattr(sync_guard, "plan_project", planning)
    sync_guard.guard_sync(
        connection(),
        tmp_path,
        push=True,
        lock_held=reason != "unlocked",
        creation_preflight=True,
    )
    assert planned == [True]

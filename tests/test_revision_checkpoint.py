import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from gorak import revision_checkpoint as checkpoint
from gorak import sync_plan
from gorak.database import OdbcSettings
from gorak.errors import ProjectError
from gorak.revision_check import RevisionCheck
from gorak.revision_observation import BoundRevisionSample, RevisionSample
from gorak.sync_guard import save_binding
from tests.test_sync_plan import setup, xml


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    connection = setup(tmp_path, monkeypatch, xml())
    generation, parent = str(uuid4()), str(uuid4())
    connection = replace(
        connection,
        revision_generation=generation,
        odbc_settings=OdbcSettings(
            "driver", "server", "port", "db", "user", "password"
        ),
    )
    save_binding(connection, tmp_path)
    health = [
        RevisionCheck("revision_structure_verified", [], generation, parent, True, True)
    ]
    sample = [
        BoundRevisionSample(
            generation, parent, RevisionSample((("server", "lane", 1),), 1)
        )
    ]
    monkeypatch.setattr(checkpoint, "check_revision_installation", lambda _: health[0])
    monkeypatch.setattr(checkpoint, "observe_installed_revisions", lambda _: sample[0])
    current = [xml()]
    exports: list[str] = []

    def export(c: Any, app: str, path: Path) -> None:
        exports.append(app)
        path.write_text(current[0])

    monkeypatch.setattr(sync_plan, "backup_application_xml", export)
    return tmp_path, connection, health, sample, current, exports


def test_quiet_status_uses_no_exports_and_matches_full_reference(
    project: tuple[Any, ...],
) -> None:
    root, connection, _, _, _, exports = project
    first, diagnostic = checkpoint.revision_plan(connection, root)
    assert diagnostic["mode"] == "full_refresh" and exports == ["example"]
    exports.clear()
    quiet, diagnostic = checkpoint.revision_plan(connection, root)
    assert quiet == first and exports == []
    assert diagnostic["mode"] == "revision_reuse" and diagnostic["history_queries"] == 0
    verified, diagnostic = checkpoint.revision_plan(
        connection, root, verify_reference=True
    )
    assert verified == quiet and diagnostic["reference_matches"] is True
    assert exports == ["example"]


def test_disk_edit_detected_without_database_export(project: tuple[Any, ...]) -> None:
    root, connection, _, _, _, exports = project
    checkpoint.revision_plan(connection, root)
    source = root / "example/proc.w4gl"
    source.write_text(source.read_text().replace("RETURN 1", "RETURN 2"))
    exports.clear()
    changes, _ = checkpoint.revision_plan(connection, root)
    assert next(c for c in changes if c.key == "example/proc").action == "push"
    assert exports == []


def test_revision_change_including_reused_lane_forces_full_refresh(
    project: tuple[Any, ...],
) -> None:
    root, connection, _, sample, current, exports = project
    checkpoint.revision_plan(connection, root)
    current[0] = xml("RETURN 3;")
    sample[0] = replace(sample[0], sample=RevisionSample((("server", "lane", 2),), 1))
    changes, diagnostic = checkpoint.revision_plan(connection, root)
    assert diagnostic["mode"] == "full_refresh" and len(exports) == 2
    assert next(c for c in changes if c.key == "example/proc").action == "pull"


@pytest.mark.parametrize(
    "fault", ["damage", "expire", "clock_reverse", "scope", "partial"]
)
def test_unusable_checkpoint_never_reuses(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    root, connection, _, sample, _, exports = project
    checkpoint.revision_plan(connection, root)
    if fault == "damage":
        (root / ".openroad/revision-checkpoint.json").write_text("{}")
    elif fault in {"expire", "clock_reverse"}:
        now = time.time()
        monkeypatch.setattr(
            time, "time", lambda: now + (901 if fault == "expire" else -10)
        )
    elif fault == "scope":
        (root / ".openroad/tracked-applications.json").write_text(
            '["example", "new_app"]'
        )
    else:
        sample[0] = replace(sample[0], sample=RevisionSample(None, 4097))
    _, report = checkpoint.revision_plan(connection, root)
    assert report["mode"] == "full_refresh" and len(exports) == 2


def test_generation_or_health_change_cannot_authorize_reuse(
    project: tuple[Any, ...],
) -> None:
    root, connection, health, _, _, exports = project
    checkpoint.revision_plan(connection, root)
    health[0] = replace(health[0], revision_id=str(uuid4()))
    with pytest.raises(ProjectError, match="generation"):
        checkpoint.revision_plan(connection, root)
    assert len(exports) == 1


def test_committing_writer_during_export_prevents_publication(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, connection, _, sample, current, _ = project

    def racing_export(c: Any, app: str, path: Path) -> None:
        path.write_text(current[0])
        sample[0] = replace(
            sample[0], sample=RevisionSample((("server", "late_transaction", 1),), 1)
        )

    monkeypatch.setattr(sync_plan, "backup_application_xml", racing_export)
    with pytest.raises(ProjectError, match="changed during"):
        checkpoint.revision_plan(connection, root)
    assert not (root / ".openroad/revision-checkpoint.json").exists()


def test_oracle_catches_untracked_mutation(project: tuple[Any, ...]) -> None:
    root, connection, _, _, current, _ = project
    checkpoint.revision_plan(connection, root)
    current[0] = xml("RETURN 9;")
    with pytest.raises(ProjectError, match="disagrees"):
        checkpoint.revision_plan(connection, root, verify_reference=True)
    assert not (root / ".openroad/revision-checkpoint.json").exists()


def test_old_checkout_and_history_pruning_need_no_server_receipts(
    project: tuple[Any, ...],
) -> None:
    root, connection, _, sample, current, exports = project
    checkpoint.revision_plan(connection, root)
    path = root / ".openroad/revision-checkpoint.json"
    old = path.read_bytes()
    current[0] = xml("RETURN 8;")
    sample[0] = replace(sample[0], sample=RevisionSample((("server", "lane", 4),), 1))
    checkpoint.revision_plan(connection, root)
    path.write_bytes(old)
    _, report = checkpoint.revision_plan(connection, root)
    assert report["mode"] == "full_refresh" and len(exports) == 3
    # There is no journal consumer, server receipt or event-history dependency.
    assert not (root / ".openroad/journal.sqlite3").exists()


def test_failed_atomic_publication_preserves_previous_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "checkpoint.json"
    checkpoint.publish_checkpoint(path, {}, {}, 1)
    original = path.read_bytes()

    def fail(*args: Any) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        checkpoint.publish_checkpoint(path, {"different": True}, {}, 2)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".revision-*"))


def test_oracle_compares_source_hashes_not_just_change_categories(
    project: tuple[Any, ...],
) -> None:
    root, connection, _, _, current, _ = project
    current[0] = xml("RETURN 3;")
    checkpoint.revision_plan(connection, root)  # Already a pull.
    current[0] = xml("RETURN 4;")  # Still a pull, but a different DB snapshot.
    with pytest.raises(ProjectError, match="disagrees"):
        checkpoint.revision_plan(connection, root, verify_reference=True)
    with pytest.raises(ProjectError, match="quarantined"):
        checkpoint.revision_plan(connection, root)


def test_observed_broken_tracking_requires_new_generation_even_after_repair(
    project: tuple[Any, ...],
) -> None:
    root, connection, health, sample, _, _ = project
    checkpoint.revision_plan(connection, root)
    original = health[0]
    health[0] = replace(original, issues=["Missing rule"])
    with pytest.raises(ProjectError):
        checkpoint.revision_plan(connection, root)
    health[0] = original
    with pytest.raises(ProjectError, match="quarantined"):
        checkpoint.revision_plan(connection, root)
    generation = str(uuid4())
    connection = replace(connection, revision_generation=generation)
    health[0] = replace(original, revision_id=generation)
    sample[0] = replace(sample[0], revision_id=generation)
    _, report = checkpoint.revision_plan(connection, root)
    assert report["mode"] == "full_refresh"


def test_push_guard_uses_checkpoint_and_blocks_database_changes(
    project: tuple[Any, ...],
) -> None:
    from gorak.sync_guard import guard_sync

    root, connection, _, sample, current, exports = project
    guard_sync(connection, root, push=True)
    exports.clear()
    guard_sync(connection, root, push=True)
    assert exports == []
    current[0] = xml("RETURN 42;")
    sample[0] = replace(sample[0], sample=RevisionSample((("server", "lane", 8),), 1))
    with pytest.raises(ProjectError, match="Sync stopped"):
        guard_sync(connection, root, push=True)
    assert exports == ["example"]
    assert not (root / ".openroad/mutation.lock").exists()


def test_corrupt_quarantine_cannot_silently_enable_reuse(
    project: tuple[Any, ...],
) -> None:
    root, connection, _, _, _, _ = project
    checkpoint.revision_plan(connection, root)
    (root / ".openroad/revision-quarantine.json").write_text('{"generation": 7}')
    with pytest.raises(ProjectError, match="Invalid revision quarantine"):
        checkpoint.revision_plan(connection, root)


def test_odbc_endpoint_change_invalidates_checkpoint_without_storing_password(
    project: tuple[Any, ...],
) -> None:
    root, connection, _, _, _, exports = project
    checkpoint.revision_plan(connection, root)
    data = (root / ".openroad/revision-checkpoint.json").read_text()
    assert '"password"' not in data
    updated = replace(
        connection,
        odbc_settings=replace(connection.odbc_settings, host="another-server"),
    )
    before = len(exports)
    _, report = checkpoint.revision_plan(updated, root)
    assert report["mode"] == "full_refresh"
    assert len(exports) > before


@pytest.mark.parametrize("through_cli", [False, True])
def test_managed_pull_reuses_owned_lock_and_installs_changed_source(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, through_cli: bool
) -> None:
    from gorak import cli, export, safe_pull
    from gorak.domain import Application
    from gorak.project import load_context

    root, connection, _, _, current, _ = project
    (root / "gorak.json").write_text('{"name":"example"}')
    current[0] = xml("RETURN 2;")

    def backup(c: Any, app: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(current[0])

    monkeypatch.setattr(export, "backup_application_xml", backup)
    monkeypatch.setattr(safe_pull, "backup_application_xml", backup)
    monkeypatch.setattr(
        safe_pull, "read_applications", lambda _: [Application("example", "", "")]
    )
    if through_cli:
        monkeypatch.chdir(root)
        monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *_: connection)
        cli.main(["sync"])
    else:
        safe_pull.sync_project(connection, load_context(root))
    assert "RETURN 2;" in (root / "example/proc.w4gl").read_text()
    for filename in ("mutation.lock", "pull.lock", "pull-pending.json"):
        assert not (root / ".openroad" / filename).exists()
    changes, _ = checkpoint.revision_plan(connection, root)
    assert all(c.action == "unchanged" for c in changes)


def test_managed_direct_pull_preserves_another_operations_lock(
    project: tuple[Any, ...],
) -> None:
    from gorak import safe_pull
    from gorak.project import load_context
    from gorak.project_lock import project_lock

    root, connection, _, _, _, _ = project
    (root / "gorak.json").write_text('{"name":"example"}')
    source = root / "example/proc.w4gl"
    original = source.read_bytes()
    with project_lock(root, "other operation"):
        lock = root / ".openroad/mutation.lock"
        owned = lock.read_bytes()
        with pytest.raises(ProjectError, match="Another Gorak operation"):
            safe_pull.sync_project(connection, load_context(root))
        assert lock.read_bytes() == owned
        assert not (root / ".openroad/pull.lock").exists()
    assert source.read_bytes() == original

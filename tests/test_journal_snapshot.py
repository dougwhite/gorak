import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from gorak import journal_snapshot, sync_plan
from gorak.database import OdbcSettings
from gorak.installation_check import InstallationCheck
from gorak.journal import JournalBatch, JournalEvent
from gorak.journal_mapping import ApplicationCandidates
from gorak.journal_observation import JournalObservation
from gorak.journal_snapshot import verify_selective_snapshot
from gorak.project import ProjectError
from tests.test_sync_plan import setup as setup_project
from tests.test_sync_plan import xml


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    connection = replace(
        setup_project(tmp_path, monkeypatch, xml()),
        sql_backend="odbc",
        odbc_settings=OdbcSettings("driver", "host", "port", "db", "user", "secret"),
    )
    from gorak.journal import acknowledgment_store

    with acknowledgment_store(tmp_path / ".openroad/journal.sqlite3"):
        pass
    identity = str(uuid4())
    health = InstallationCheck(
        "capture_only_inventory_present", identity, [], schema_version=2
    )
    monkeypatch.setattr(journal_snapshot, "binding_status", lambda *a: "verified")
    monkeypatch.setattr(journal_snapshot, "check_installation", lambda *a: health)
    monkeypatch.setattr(
        journal_snapshot, "poll_journal", lambda *a, **kw: JournalBatch(identity, (), 0)
    )
    monkeypatch.setattr(
        journal_snapshot,
        "observe_journal",
        lambda *a: JournalObservation(2, identity, 0, None),
    )
    mapping = [ApplicationCandidates((), False, (), 0)]
    monkeypatch.setattr(
        journal_snapshot, "map_applications", lambda *a, **kw: mapping[0]
    )
    monkeypatch.setattr(journal_snapshot, "read_ancestry", lambda *a: ())
    database = [xml()]
    exports: list[str] = []

    def export(connection: Any, app: str, path: Path) -> None:
        exports.append(app)
        path.write_text(database[0])

    monkeypatch.setattr(sync_plan, "backup_application_xml", export)
    return tmp_path, connection, mapping, database, exports


def test_bootstrap_then_reuse_verified_against_full_reference(
    project: tuple[Any, ...],
) -> None:
    root, connection, _, _, exports = project
    baseline = (root / ".openroad/example/example.xml").read_bytes()
    first = verify_selective_snapshot(connection, root)
    assert first["mode"] == "full_fallback"
    assert exports == ["example"]
    exports.clear()
    second = verify_selective_snapshot(connection, root)
    assert second["mode"] == "selective_verified"
    assert second["reused_applications"] == ["example"]
    assert exports == [
        "example"
    ]  # Mandatory full reference; selective pass reused XML.
    assert (root / ".openroad/example/example.xml").read_bytes() == baseline
    assert second["acknowledged"] is False


def test_missed_event_is_caught_and_full_snapshot_replaces_stale_cache(
    project: tuple[Any, ...],
) -> None:
    root, connection, _, database, _ = project
    verify_selective_snapshot(connection, root)
    database[0] = xml("RETURN 7;")
    result = verify_selective_snapshot(connection, root)
    assert result["mode"] == "full_fallback"
    assert result["selective_matches_reference"] is False
    assert result["fallback_reason"] == "selective_snapshot_differs_from_full_reference"
    pointer = json.loads((root / ".openroad/journal-snapshot.json").read_text())
    reference = (
        root / ".openroad/journal-snapshots" / pointer["operation"] / "reference/0.xml"
    )
    assert reference.read_text() == database[0]


def test_mapped_app_is_refreshed_and_matches_reference(
    project: tuple[Any, ...],
) -> None:
    root, connection, mapping, database, exports = project
    verify_selective_snapshot(connection, root)
    mapping[0] = ApplicationCandidates(("example",), False, (), 1)
    database[0] = xml("RETURN 7;")
    exports.clear()
    result = verify_selective_snapshot(connection, root)
    assert result["selective_matches_reference"] is True
    assert result["reused_applications"] == []
    assert exports == ["example", "example"]


def test_unresolved_mapping_uses_one_full_export(project: tuple[Any, ...]) -> None:
    root, connection, mapping, _, exports = project
    verify_selective_snapshot(connection, root)
    mapping[0] = ApplicationCandidates((), True, (), 0)
    exports.clear()
    result = verify_selective_snapshot(connection, root)
    assert result["fallback_reason"] == "unresolved_events"
    assert exports == ["example"]


def test_corrupt_cache_falls_back_without_using_it(project: tuple[Any, ...]) -> None:
    root, connection, _, _, _ = project
    verify_selective_snapshot(connection, root)
    pointer = json.loads((root / ".openroad/journal-snapshot.json").read_text())
    file = (
        root / ".openroad/journal-snapshots" / pointer["operation"] / "reference/0.xml"
    )
    file.write_text("broken")
    assert (
        verify_selective_snapshot(connection, root)["fallback_reason"]
        == "missing_or_invalid_snapshot"
    )


def test_failed_reference_export_does_not_replace_pointer(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, connection, _, _, _ = project
    verify_selective_snapshot(connection, root)
    pointer = (root / ".openroad/journal-snapshot.json").read_bytes()

    def fail(*args: Any) -> None:
        raise ProjectError("export failed")

    monkeypatch.setattr(sync_plan, "backup_application_xml", fail)
    with pytest.raises(ProjectError, match="export failed"):
        verify_selective_snapshot(connection, root)
    assert (root / ".openroad/journal-snapshot.json").read_bytes() == pointer


def test_concurrent_disk_change_prevents_publication(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, connection, _, database, _ = project

    def edit(connection: Any, app: str, path: Path) -> None:
        path.write_text(database[0])
        (root / "example/proc.w4gl").write_text("concurrent edit")

    monkeypatch.setattr(sync_plan, "backup_application_xml", edit)
    with pytest.raises(ProjectError, match="snapshot not published"):
        verify_selective_snapshot(connection, root)
    assert not (root / ".openroad/journal-snapshot.json").exists()


def test_removed_remote_application_is_not_kept_from_cache(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, connection, _, _, _ = project
    verify_selective_snapshot(connection, root)
    monkeypatch.setattr(sync_plan, "read_applications", lambda *a: [])
    result = verify_selective_snapshot(connection, root)
    assert result["selective_matches_reference"] is True
    assert result["full_reference_applications"] == []
    assert result["changes"]


def test_durability_failure_preserves_old_snapshot_pointer(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, connection, _, _, _ = project
    verify_selective_snapshot(connection, root)
    pointer = (root / ".openroad/journal-snapshot.json").read_bytes()

    def fail(*args: Any) -> None:
        raise OSError("flush failed")

    monkeypatch.setattr(journal_snapshot, "persist_comparison", fail)
    with pytest.raises(OSError, match="flush failed"):
        verify_selective_snapshot(connection, root)
    assert (root / ".openroad/journal-snapshot.json").read_bytes() == pointer


def test_snapshot_cannot_escape_cache_directory(project: tuple[Any, ...]) -> None:
    root, connection, _, _, _ = project
    verify_selective_snapshot(connection, root)
    path = root / ".openroad/journal-snapshot.json"
    pointer = json.loads(path.read_text())
    pointer["operation"] = "../../outside"
    path.write_text(json.dumps(pointer))
    result = verify_selective_snapshot(connection, root)
    assert result["fallback_reason"] == "missing_or_invalid_snapshot"


@pytest.mark.parametrize("after_count,after_max", [(2, 10), (2, 11), (0, None)])
def test_journal_change_during_export_preserves_pointer(
    project: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
    after_count: int,
    after_max: int | None,
) -> None:
    root, connection, _, _, _ = project
    verify_selective_snapshot(connection, root)
    pointer = root / ".openroad/journal-snapshot.json"
    original = pointer.read_bytes()
    identity = json.loads(original)["installation_id"]
    observations = iter(
        [
            JournalObservation(2, identity, 1, 10),
            JournalObservation(2, identity, after_count, after_max),
        ]
    )
    monkeypatch.setattr(
        journal_snapshot, "observe_journal", lambda *a: next(observations)
    )
    with pytest.raises(ProjectError, match="Journal changed during observation"):
        verify_selective_snapshot(connection, root)
    assert pointer.read_bytes() == original
    assert not list(pointer.parent.glob(".journal-snapshot-*.tmp"))


def test_full_batch_disables_selective_reuse(
    project: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, connection, _, _, exports = project
    first = verify_selective_snapshot(connection, root)
    identity = str(first["installation_id"])
    monkeypatch.setattr(
        journal_snapshot,
        "poll_journal",
        lambda *a, **kw: JournalBatch(
            identity,
            (JournalEvent(1, "ii_entities", "u", {}, {}),),
            1,
        ),
    )
    exports.clear()
    result = verify_selective_snapshot(connection, root, limit=1)
    assert result["fallback_reason"] == "event_batch_at_limit"
    assert result["reused_applications"] == []
    assert exports == ["example"]


def test_replaced_installation_during_observation_preserves_pointer(
    project: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, connection, _, _, _ = project
    first = verify_selective_snapshot(connection, root)
    pointer = root / ".openroad/journal-snapshot.json"
    original = pointer.read_bytes()
    observations = iter(
        [
            JournalObservation(2, str(first["installation_id"]), 0, None),
            JournalObservation(2, str(uuid4()), 0, None),
        ]
    )
    monkeypatch.setattr(
        journal_snapshot, "observe_journal", lambda *a: next(observations)
    )
    with pytest.raises(ProjectError, match="Journal changed"):
        verify_selective_snapshot(connection, root)
    assert pointer.read_bytes() == original


def test_disconnect_at_final_observation_preserves_pointer(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, connection, _, _, _ = project
    first = verify_selective_snapshot(connection, root)
    pointer = root / ".openroad/journal-snapshot.json"
    original = pointer.read_bytes()
    calls = 0

    def observe(*args: Any) -> JournalObservation:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("connection lost")
        return JournalObservation(2, str(first["installation_id"]), 0, None)

    monkeypatch.setattr(journal_snapshot, "observe_journal", observe)
    with pytest.raises(RuntimeError, match="connection lost"):
        verify_selective_snapshot(connection, root)
    assert pointer.read_bytes() == original
    assert not list(pointer.parent.glob(".journal-snapshot-*.tmp"))


@pytest.mark.parametrize("same_identity", [False, True])
def test_rebootstrap_replaces_old_binding_and_preserves_acknowledgments_in_archive(
    project: tuple[Any, ...],
    same_identity: bool,
) -> None:
    from gorak.journal import acknowledgment_store, bind_store
    from gorak.journal_server import consumer_identity

    root, connection, _, _, exports = project
    first = verify_selective_snapshot(connection, root)
    baseline = (root / ".openroad/example/example.xml").read_bytes()
    with acknowledgment_store(root / ".openroad/journal.sqlite3") as store:
        bind_store(
            store, str(first["installation_id"]) if same_identity else str(uuid4())
        )
        old_consumer = consumer_identity(store)
        store.execute("insert into acknowledged values (42)")
        store.commit()
    exports.clear()
    report = verify_selective_snapshot(connection, root, rebootstrap=True)
    assert report["fallback_reason"] == "explicit_rebootstrap"
    assert report["rebootstrapped"] is True
    assert exports == ["example"]
    with acknowledgment_store(root / ".openroad/journal.sqlite3") as store:
        assert consumer_identity(store) != old_consumer
        assert store.execute("select * from acknowledged").fetchall() == []
        assert store.execute("select id from installation").fetchall() == [
            (report["installation_id"],)
        ]
    with acknowledgment_store(
        Path(str(report["previous_state"])) / "journal.sqlite3"
    ) as store:
        assert consumer_identity(store) == old_consumer
        assert store.execute("select * from acknowledged").fetchall() == [(42,)]
    assert (root / ".openroad/example/example.xml").read_bytes() == baseline


def test_rebootstrap_export_failure_keeps_current_state(
    project: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, connection, _, _, _ = project
    verify_selective_snapshot(connection, root)
    pointer = root / ".openroad/journal-snapshot.json"
    journal = root / ".openroad/journal.sqlite3"
    old_pointer, old_journal = pointer.read_bytes(), journal.read_bytes()

    def fail(*args: Any) -> None:
        raise ProjectError("export failed")

    monkeypatch.setattr(sync_plan, "backup_application_xml", fail)
    with pytest.raises(ProjectError, match="export failed"):
        verify_selective_snapshot(connection, root, rebootstrap=True)
    assert pointer.read_bytes() == old_pointer
    assert journal.read_bytes() == old_journal


def test_ancestry_corruption_discards_snapshot(project: tuple[Any, ...]) -> None:
    root, connection, _, _, _ = project
    verify_selective_snapshot(connection, root)
    pointer = json.loads((root / ".openroad/journal-snapshot.json").read_text())
    ancestry = (
        root / ".openroad/journal-snapshots" / pointer["operation"] / "ancestry.json"
    )
    ancestry.write_text('[[1,0,0,"wrong","appsource"]]')
    result = verify_selective_snapshot(connection, root)
    assert result["fallback_reason"] == "missing_or_invalid_snapshot"
    assert result["historical_entities_used"] == 0


def test_rebootstrap_never_uses_old_ancestry(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.journal_mapping import Entity

    root, connection, _, _, _ = project
    monkeypatch.setattr(
        journal_snapshot,
        "read_ancestry",
        lambda *a: (Entity(1, 0, 0, "example", "appsource"),),
    )
    verify_selective_snapshot(connection, root)
    result = verify_selective_snapshot(connection, root, rebootstrap=True)
    assert result["historical_entities_used"] == 0
    assert result["captured_entities"] == 1


def test_ancestry_capture_failure_preserves_pointer(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, connection, _, _, _ = project
    verify_selective_snapshot(connection, root)
    pointer = root / ".openroad/journal-snapshot.json"
    original = pointer.read_bytes()

    def fail(*args: Any) -> None:
        raise RuntimeError("metadata disconnected")

    monkeypatch.setattr(journal_snapshot, "read_ancestry", fail)
    with pytest.raises(RuntimeError, match="metadata disconnected"):
        verify_selective_snapshot(connection, root)
    assert pointer.read_bytes() == original


def test_old_snapshot_format_rebuilds_history(project: tuple[Any, ...]) -> None:
    root, connection, _, _, _ = project
    verify_selective_snapshot(connection, root)
    path = root / ".openroad/journal-snapshot.json"
    pointer = json.loads(path.read_text())
    pointer["version"] = 1
    path.write_text(json.dumps(pointer))
    result = verify_selective_snapshot(connection, root)
    assert result["fallback_reason"] == "missing_or_invalid_snapshot"
    assert json.loads(path.read_text())["version"] == 3


def test_validated_ancestry_reaches_mapper(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.journal_mapping import Entity

    root, connection, _, _, _ = project
    history = (Entity(1, 0, 0, "example", "appsource"),)
    monkeypatch.setattr(journal_snapshot, "read_ancestry", lambda *a: history)
    verify_selective_snapshot(connection, root)
    received = []

    def map_batch(
        *args: Any, historical_entities: tuple[Entity, ...]
    ) -> ApplicationCandidates:
        received.append(historical_entities)
        return ApplicationCandidates((), False, (), 0)

    monkeypatch.setattr(journal_snapshot, "map_applications", map_batch)
    result = verify_selective_snapshot(connection, root)
    assert received == [history]
    assert result["historical_entities_used"] == 1


def test_over_budget_ancestry_does_not_block_full_observation(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, connection, _, _, _ = project
    monkeypatch.setattr(journal_snapshot, "read_ancestry", lambda *a: None)
    first = verify_selective_snapshot(connection, root)
    second = verify_selective_snapshot(connection, root)
    assert first["captured_entities"] is None
    assert second["historical_entities_used"] == 0
    assert second["incremental_ready"] is False


def test_exact_limit_with_proven_exhaustion_can_verify_selectively(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, connection, _, _, _ = project
    first = verify_selective_snapshot(connection, root)
    monkeypatch.setattr(
        journal_snapshot,
        "poll_journal",
        lambda *a, **kw: JournalBatch(
            str(first["installation_id"]),
            (JournalEvent(1, "ii_entities", "u", {}, {}),),
            1,
            True,
        ),
    )
    result = verify_selective_snapshot(connection, root, limit=1)
    assert result["pending_set_complete"] is True
    assert result["mode"] == "selective_verified"
    assert result["selective_matches_reference"] is True


def test_routine_snapshot_keeps_general_consumer_unchanged(
    project: tuple[Any, ...],
) -> None:
    root, connection, _, _, _ = project
    general = root / ".openroad/journal.sqlite3"
    before = general.read_bytes()
    first = verify_selective_snapshot(connection, root)
    second = verify_selective_snapshot(connection, root)
    assert general.read_bytes() == before
    assert second["general_consumer_unchanged"] is True
    assert first["observer_consumer_id"] == second["observer_consumer_id"]


def test_observer_corruption_rebuilds_full_snapshot(project: tuple[Any, ...]) -> None:
    root, connection, _, _, _ = project
    first = verify_selective_snapshot(connection, root)
    pointer = json.loads((root / ".openroad/journal-snapshot.json").read_text())
    observer = (
        root / ".openroad/journal-snapshots" / pointer["operation"] / "observer.sqlite3"
    )
    observer.write_bytes(b"corrupt")
    second = verify_selective_snapshot(connection, root)
    assert second["fallback_reason"] == "missing_or_invalid_snapshot"
    assert second["observer_consumer_id"] != first["observer_consumer_id"]


def test_unpublished_observer_checkpoint_replays_on_snapshot_retry(
    project: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.journal import poll_journal
    from tests.test_journal_server import Server

    root, connection, _, _, _ = project
    server = Server()
    identity = str(verify_selective_snapshot(connection, root)["installation_id"])
    server.db.execute(
        'update "$ingres".gorak_tracking_install set installation_id=?', (identity,)
    )
    server.db.commit()
    monkeypatch.setattr(
        journal_snapshot,
        "poll_journal",
        lambda settings, store, limit, **kw: poll_journal(
            settings, store, limit, server.factory, **kw
        ),
    )
    verify_selective_snapshot(connection, root)
    pointer = root / ".openroad/journal-snapshot.json"
    original = pointer.read_bytes()
    server.add(1)
    from gorak.journal_reconcile import persist_comparison as persist

    def fail(*args: Any) -> None:
        raise OSError("receipt flush failed")

    monkeypatch.setattr(journal_snapshot, "persist_comparison", fail)
    with pytest.raises(OSError, match="receipt flush failed"):
        verify_selective_snapshot(connection, root)
    assert pointer.read_bytes() == original
    assert server.db.execute(
        'select count(*) from "$ingres".gorak_journal_acks'
    ).fetchone() == (0,)
    monkeypatch.setattr(journal_snapshot, "persist_comparison", persist)
    retry = verify_selective_snapshot(connection, root)
    assert retry["observer_checkpointed_events"] == 1
    following = verify_selective_snapshot(connection, root)
    assert following["observer_checkpointed_events"] == 0

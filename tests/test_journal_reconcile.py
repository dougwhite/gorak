import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from gorak import journal, journal_reconcile
from gorak.connection import OpenRoadConnection
from gorak.database import OdbcSettings
from gorak.installation_check import InstallationCheck
from gorak.journal import JournalBatch, JournalEvent
from gorak.journal_reconcile import reconcile_journal
from gorak.project import ProjectError
from gorak.sync_plan import Change


@pytest.fixture
def setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, OpenRoadConnection, list[Change]]:
    root = tmp_path
    (root / "source.txt").write_text("source")
    cache = root / ".openroad" / "example"
    cache.mkdir(parents=True)
    (cache / "example.xml").write_text("old common baseline")
    identity = str(uuid4())
    settings = OdbcSettings("driver", "host", "port", "source_db", "user", "secret")
    connection = OpenRoadConnection(
        backend="local",
        remote_host=None,
        vnode="node",
        database="source_db",
        sql_backend="odbc",
        odbc_settings=settings,
    )
    monkeypatch.setattr(journal_reconcile, "binding_status", lambda *a: "verified")
    monkeypatch.setattr(
        journal_reconcile,
        "check_installation",
        lambda *a: InstallationCheck(
            "capture_only_inventory_present", identity, [], schema_version=2
        ),
    )
    changes = [Change("example/procedure", "unchanged", "unchanged", "unchanged")]

    def plan(
        connection: OpenRoadConnection, root: Path, *, capture_dir: Path
    ) -> list[Change]:
        capture_dir.mkdir()
        (capture_dir / "0.xml").write_text("<source_snapshot/>")
        (capture_dir / "applications.json").write_text('{"example":"0.xml"}')
        return changes

    def poll(
        settings: OdbcSettings, store: sqlite3.Connection, *a: object
    ) -> JournalBatch:
        journal.bind_store(store, identity)
        return JournalBatch(
            identity,
            tuple(
                JournalEvent(i, "ii_entities", "u", {}, {})
                for i in (3, 2)
                if not store.execute(
                    "select 1 from acknowledged where event_id=?", (i,)
                ).fetchone()
            ),
            2,
        )

    monkeypatch.setattr(journal_reconcile, "plan_project", plan)
    monkeypatch.setattr(journal, "poll_journal", poll)
    return root, connection, changes


def acknowledged(root: Path) -> list[int]:
    with sqlite3.connect(root / ".openroad" / "journal.sqlite3") as store:
        return [
            row[0]
            for row in store.execute(
                "select event_id from acknowledged order by event_id"
            )
        ]


def test_comparison_evidence_precedes_ack_and_common_baselines_stay_intact(
    setup: tuple[Path, OpenRoadConnection, list[Change]],
) -> None:
    root, connection, _ = setup
    result = reconcile_journal(connection, root)
    assert result["processed_events"] == 2
    assert acknowledged(root) == [2, 3]
    report = json.loads(Path(str(result["comparison"])).read_text())
    assert report["disk_database_agree"] is True
    assert (root / ".openroad/example/example.xml").read_text() == "old common baseline"
    assert (root / "source.txt").read_text() == "source"
    with sqlite3.connect(root / ".openroad/journal.sqlite3") as store:
        receipts = store.execute(
            "select report_path from comparison_receipts"
        ).fetchall()
    assert len(receipts) == 2
    assert all((root / row[0]).exists() for row in receipts)
    assert reconcile_journal(connection, root)["processed_events"] == 0


@pytest.mark.parametrize("action", ["push", "pull", "conflict"])
def test_differences_save_report_but_leave_events_pending(
    setup: tuple[Path, OpenRoadConnection, list[Change]],
    action: str,
) -> None:
    root, connection, changes = setup
    from gorak.sync_plan import Action

    changes[:] = [
        Change("example/procedure", cast(Action, action), "modified", "modified")
    ]
    with pytest.raises(ProjectError, match="events remain pending"):
        reconcile_journal(connection, root)
    assert acknowledged(root) == []
    report = next((root / ".openroad/journal-comparisons").glob("*/comparison.json"))
    assert json.loads(report.read_text())["disk_database_agree"] is False


def test_concurrent_disk_edit_prevents_acknowledgment(
    setup: tuple[Path, OpenRoadConnection, list[Change]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, connection, _ = setup
    original = cast(
        Callable[..., list[Change]], vars(journal_reconcile)["plan_project"]
    )

    def edited(
        connection: OpenRoadConnection, root: Path, *, capture_dir: Path
    ) -> list[Change]:
        changes = original(connection, root, capture_dir=capture_dir)
        (root / "source.txt").write_text("concurrent edit")
        return changes

    monkeypatch.setattr(journal_reconcile, "plan_project", edited)
    with pytest.raises(ProjectError, match="events remain pending"):
        reconcile_journal(connection, root)
    assert acknowledged(root) == []


def test_durability_failure_leaves_events_pending(
    setup: tuple[Path, OpenRoadConnection, list[Change]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, connection, _ = setup

    def fail(*args: object) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(journal_reconcile, "persist_comparison", fail)
    with pytest.raises(OSError, match="fsync failed"):
        reconcile_journal(connection, root)
    assert acknowledged(root) == []


def test_binding_required_before_poll(
    setup: tuple[Path, OpenRoadConnection, list[Change]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, connection, _ = setup
    monkeypatch.setattr(journal_reconcile, "binding_status", lambda *a: "unbound")
    with pytest.raises(ProjectError, match="verified sync target"):
        reconcile_journal(connection, root)
    assert not (root / ".openroad/journal.sqlite3").exists()


def test_ack_failure_replays_with_fresh_evidence(
    setup: tuple[Path, OpenRoadConnection, list[Change]],
) -> None:
    root, connection, _ = setup
    with journal.acknowledgment_store(root / ".openroad/journal.sqlite3") as store:
        store.execute(
            "create trigger fail_ack before insert on acknowledged begin select raise(abort, 'disk failure'); end"
        )
    with pytest.raises(ProjectError, match="storage failed"):
        reconcile_journal(connection, root)
    assert acknowledged(root) == []
    with sqlite3.connect(root / ".openroad/journal.sqlite3") as store:
        store.execute("drop trigger fail_ack")
    assert reconcile_journal(connection, root)["processed_events"] == 2
    assert (
        len(list((root / ".openroad/journal-comparisons").glob("*/comparison.json")))
        == 2
    )


def test_edit_while_flushing_evidence_does_not_ack(
    setup: tuple[Path, OpenRoadConnection, list[Change]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, connection, _ = setup
    persist = journal_reconcile.persist_comparison

    def edit(directory: Path, report: dict[str, object]) -> None:
        persist(directory, report)
        (root / "source.txt").write_text("late edit")

    monkeypatch.setattr(journal_reconcile, "persist_comparison", edit)
    with pytest.raises(ProjectError, match="persisting comparison"):
        reconcile_journal(connection, root)
    assert acknowledged(root) == []

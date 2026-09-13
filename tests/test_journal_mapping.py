from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from gorak.database import OdbcSettings
from gorak.journal import MARKER_SQL, JournalBatch, JournalEvent
from gorak.journal_mapping import map_applications
from gorak.project import ProjectError

SETTINGS = OdbcSettings("driver", "host", "port", "source_db", "user", "secret")
IDENTITY = str(uuid4())


def make_event(
    table: str = "ii_srcobj_encoded",
    action: str = "u",
    old: dict[str, int | str | None] | None = None,
    new: dict[str, int | str | None] | None = None,
) -> JournalEvent:
    return JournalEvent(
        1, table, action, old or {"object_id": 3}, new or {"object_id": 3}
    )


def run(
    events: list[JournalEvent], rows: dict[int, tuple[Any, ...]]
) -> tuple[Any, MagicMock]:
    engine = MagicMock()

    def execute(statement: Any, params: Any = None) -> Any:
        if str(statement) == MARKER_SQL:
            return [(2, IDENTITY, "capture_only")]
        if params:
            return [rows[i] for i in params.values() if i in rows]
        return []

    engine.connect.return_value.__enter__.return_value.execute.side_effect = execute
    result = map_applications(
        SETTINGS,
        JournalBatch(IDENTITY, tuple(events), len(events)),
        engine_factory=lambda _: engine,
    )
    return result, engine


def graph() -> dict[int, tuple[Any, ...]]:
    return {
        3: (3, 0, 2, "procedure", "proc4glsource"),
        2: (2, 1, 0, "procedure", "proc4glsource"),
        1: (1, 0, 0, "Example", "appsource"),
    }


def test_encoded_version_resolves_through_base_and_parent() -> None:
    result, engine = run([make_event()], graph())
    assert result.applications == ("example",)
    assert not result.full_comparison
    assert result.metadata_queries == 3
    engine.dispose.assert_called_once()
    queries = engine.connect.return_value.__enter__.return_value.execute.call_args_list
    assert all("text_string" not in str(q) for q in queries)


def test_move_invalidates_both_old_and_new_applications() -> None:
    rows = graph()
    rows[2] = (2, 4, 0, "procedure", "proc4glsource")
    rows[4] = (4, 0, 0, "Other", "appsource")
    result, _ = run(
        [
            make_event(
                "ii_entities",
                old={"object_id": 2, "parent_id": 1, "object_type": "proc4glsource"},
                new={"object_id": 2, "parent_id": 4, "object_type": "proc4glsource"},
            )
        ],
        rows,
    )
    assert result.applications == ("example", "other")
    assert not result.full_comparison


def test_app_rename_retains_both_names() -> None:
    result, _ = run(
        [
            make_event(
                "ii_entities",
                old={
                    "object_id": 1,
                    "object_name": "before",
                    "object_type": "appsource",
                },
                new={
                    "object_id": 1,
                    "object_name": "after",
                    "object_type": "appsource",
                },
            )
        ],
        {},
    )
    assert result.applications == ("after", "before")
    assert not result.full_comparison


def test_deleted_component_resolves_from_sibling_tombstones() -> None:
    events = [
        make_event("ii_srcobj_encoded", "d"),
        make_event(
            "ii_entities",
            "d",
            old={"object_id": 3, "base_id": 2, "object_type": "proc4glsource"},
        ),
        make_event(
            "ii_entities",
            "d",
            old={"object_id": 2, "parent_id": 1, "object_type": "proc4glsource"},
        ),
        make_event(
            "ii_entities",
            "d",
            old={
                "object_id": 1,
                "object_name": "deleted_app",
                "object_type": "appsource",
            },
        ),
    ]
    result, _ = run(events, {})
    assert result.applications == ("deleted_app",)
    assert not result.full_comparison


@pytest.mark.parametrize(
    "table", ["ii_stored_strings", "ii_stored_nstrings", "ii_stored_bitmaps"]
)
def test_shared_storage_never_uses_colliding_entity_id(table: str) -> None:
    result, _ = run([make_event(table)], graph())
    assert result.full_comparison
    assert not result.applications
    assert result.metadata_queries == 0


def test_missing_tombstone_in_bounded_batch_requires_full_comparison() -> None:
    result, _ = run([make_event("ii_srcobj_encoded", "d")], {})
    assert result.full_comparison


def test_cycle_falls_back_instead_of_guessing() -> None:
    result, _ = run([make_event()], {3: (3, 2, 0, "", ""), 2: (2, 3, 0, "", "")})
    assert result.full_comparison


def test_include_maps_declaring_application_not_include_name() -> None:
    result, _ = run(
        [
            make_event(
                "ii_incl_apps",
                "i",
                new={"object_id": 1, "object_name": "unrelated_include"},
            )
        ],
        graph(),
    )
    assert result.applications == ("example",)
    assert not result.full_comparison


def test_changed_installation_stops_mapping() -> None:
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.return_value = [
        (2, str(uuid4()), "capture_only")
    ]
    with pytest.raises(ProjectError, match="installation changed"):
        map_applications(
            SETTINGS,
            JournalBatch(IDENTITY, (make_event(),), 1),
            engine_factory=lambda _: engine,
        )
    engine.dispose.assert_called_once()


def test_current_row_cannot_prove_deleted_identity_was_not_reused() -> None:
    result, _ = run([make_event("ii_components", "d")], graph())
    assert result.applications == ("example",)
    assert result.full_comparison


def test_mapping_candidates_cover_full_comparison_changed_application(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.sync_plan import plan_project
    from tests.test_sync_plan import setup, xml

    connection = setup(tmp_path, monkeypatch, xml("RETURN 3;"))
    expected = {
        change.key.split("/")[0]
        for change in plan_project(connection, tmp_path)
        if change.database != "unchanged"
    }
    result, _ = run([make_event()], graph())
    assert expected
    assert expected <= set(result.applications)
    assert not result.full_comparison


def test_batched_resolution_deduplicates_shared_ancestry() -> None:
    events = [make_event() for _ in range(100)]
    result, _ = run(events, graph())
    assert result.metadata_queries == 3
    assert len(result.events) == 100


def test_unresolvable_branch_is_not_hidden_by_resolvable_branch() -> None:
    rows = graph()
    rows[3] = (3, 999, 2, "procedure", "proc4glsource")
    result, _ = run([make_event()], rows)
    assert result.applications == ("example",)
    assert result.full_comparison


def test_traversal_limit_forces_full_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gorak import journal_mapping

    monkeypatch.setattr(journal_mapping, "MAX_DEPTH", 2)
    result, _ = run([make_event()], graph())
    assert result.full_comparison


def test_installation_replaced_after_lookup_is_rejected() -> None:
    engine = MagicMock()
    markers = iter([IDENTITY, str(uuid4())])

    def execute(statement: Any, params: Any = None) -> Any:
        if str(statement) == MARKER_SQL:
            return [(2, next(markers), "capture_only")]
        return []

    engine.connect.return_value.__enter__.return_value.execute.side_effect = execute
    with pytest.raises(ProjectError, match="installation changed"):
        map_applications(
            SETTINGS,
            JournalBatch(IDENTITY, (make_event(),), 1),
            engine_factory=lambda _: engine,
        )
    engine.dispose.assert_called_once()

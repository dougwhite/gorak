from typing import Any

import pytest

from gorak import procedure_snapshot as snapshot
from gorak.affected_source import AffectedSource
from gorak.encoded_source import UnsupportedSource
from gorak.journal import JournalEvent
from tests.test_affected_source import SETTINGS

RECORD = {
    "identity": 12,
    "base_id": 11,
    "version_metadata": "version",
    "base_metadata": "base",
}


def test_only_version_description_is_exempted_from_metadata_guard() -> None:
    old = {"entity_id": 12, "short_remark": "old", "unknown_column": "old"}
    edited = dict(old, short_remark="new")
    assert snapshot.metadata_hash(old, version=True) == snapshot.metadata_hash(
        edited, version=True
    )
    assert snapshot.metadata_hash(old) != snapshot.metadata_hash(edited)
    assert snapshot.metadata_hash(old, version=True) != snapshot.metadata_hash(
        dict(old, unknown_column="new"), version=True
    )


def selection(
    table: str = "ii_entities", action: str = "u", identity: int = 12
) -> AffectedSource:
    return AffectedSource(
        (
            JournalEvent(
                101, table, action, {"object_id": identity}, {"object_id": identity}
            ),
        ),
        (identity,),
        101,
    )


def test_refresh_reads_only_candidates_and_preserves_other_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def observe(*args: Any) -> tuple[dict[str, Any], str]:
        calls.append(args[1:3])
        return RECORD, "new"

    monkeypatch.setattr(snapshot, "observe_procedure", observe)
    source = {"maximum": 100, "objects": {"app/probe": RECORD}}
    inventory = {"app": "app", "app/probe": "old", "app/frame": "frame"}
    updated, checkpoint = snapshot.refresh_procedures(
        SETTINGS, source, selection(), inventory
    )
    assert updated == dict(inventory, **{"app/probe": "new"})
    assert inventory["app/probe"] == "old" and source["maximum"] == 100
    assert checkpoint["maximum"] == 101 and calls == [(12, 11)]


@pytest.mark.parametrize(
    "candidate",
    [
        selection(identity=99),
        selection(action="d"),
        selection(table="ii_applications"),
        AffectedSource(fallback="missing_range"),
    ],
)
def test_unknown_ownership_deletion_or_unsupported_table_falls_back(
    candidate: AffectedSource,
) -> None:
    with pytest.raises(UnsupportedSource):
        snapshot.refresh_procedures(
            SETTINGS, {"objects": {"app/probe": RECORD}}, candidate, {}
        )


def test_changed_metadata_discards_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        snapshot,
        "observe_procedure",
        lambda *a: (dict(RECORD, base_metadata="changed"), "new"),
    )
    with pytest.raises(UnsupportedSource, match="metadata_changed"):
        snapshot.refresh_procedures(
            SETTINGS,
            {"objects": {"app/probe": RECORD}},
            selection(),
            {"app/probe": "old"},
        )


@pytest.mark.parametrize("oracle", ["decoded", "different"])
def test_bootstrap_enrolls_only_full_oracle_agreement(
    monkeypatch: pytest.MonkeyPatch, oracle: str
) -> None:
    from tests.test_affected_source import Engine

    class BootstrapEngine(Engine):
        def scalar(self) -> int:
            return 100

        def execute(self, query: Any, params: Any = None) -> "BootstrapEngine":
            self.queries.append(str(query))
            if params:
                assert params == {"app": "app"}
            return self

    engine = BootstrapEngine([[12, 11, "probe", 10, 9]])
    monkeypatch.setattr(
        snapshot, "observe_application", lambda *a: {"identity": 10, "base_id": 9}
    )
    monkeypatch.setattr(snapshot, "observe_procedure", lambda *a: (RECORD, "decoded"))
    result = snapshot.bootstrap_procedures(
        SETTINGS, ["app"], {"app/probe": oracle}, lambda _: engine
    )
    assert result["maximum"] == 100
    assert result["objects"] == ({"app/probe": RECORD} if oracle == "decoded" else {})
    assert engine.closed and engine.disposed


def test_entity_reader_rejects_ambiguous_current_identity() -> None:
    from tests.test_affected_source import Engine

    class MetadataEngine(Engine):
        def keys(self) -> list[str]:
            return ["entity_id", "short_remark"]

        def execute(self, query: Any, params: Any = None) -> "MetadataEngine":
            assert params == {"identity": 12}
            return self

    engine = MetadataEngine([[12, "first"], [12, "second"]])
    with pytest.raises(UnsupportedSource, match="ambiguous"):
        snapshot.entity_row(engine, 12)
    assert engine.closed


def test_component_bookkeeping_does_not_hide_source_metadata_changes() -> None:
    original = {
        "entity_id": 12,
        "alter_count": 1,
        "current_make": 0,
        "value_string": "source",
        "data_type": "integer",
    }
    compiled = dict(original, alter_count=2, current_make=3)
    assert snapshot.metadata_hash(original, component=True) == snapshot.metadata_hash(
        compiled, component=True
    )
    assert snapshot.metadata_hash(original, component=True) != snapshot.metadata_hash(
        dict(compiled, value_string="changed"), component=True
    )


@pytest.mark.parametrize("changed", [False, True])
def test_workbench_application_row_update_must_preserve_source_metadata(
    monkeypatch: pytest.MonkeyPatch, changed: bool
) -> None:
    application = {"identity": 10, "base_id": 9, "application_metadata": "before"}
    monkeypatch.setattr(
        snapshot,
        "observe_application",
        lambda *a: dict(
            application, application_metadata="after" if changed else "before"
        ),
    )
    source = {"objects": {}, "applications": {"app": application}}
    candidate = selection(table="ii_applications", identity=10)
    if changed:
        with pytest.raises(
            UnsupportedSource, match="application_identity_or_metadata_changed"
        ):
            snapshot.refresh_procedures(SETTINGS, source, candidate, {"app": "oracle"})
    else:
        inventory, _ = snapshot.refresh_procedures(
            SETTINGS, source, candidate, {"app": "oracle"}
        )
        assert inventory == {"app": "oracle"}


def test_application_encoded_storage_is_not_ignored() -> None:
    with pytest.raises(UnsupportedSource, match="unsupported_affected_table"):
        snapshot.refresh_procedures(
            SETTINGS,
            {"objects": {}, "applications": {"app": {"identity": 10, "base_id": 9}}},
            selection(table="ii_srcobj_encoded", identity=10),
            {"app": "oracle"},
        )


def test_application_bookkeeping_guard_keeps_starting_component() -> None:
    old = {"proc_start": "probe", "alter_count": 1, "alter_date": "old"}
    updated = dict(old, alter_count=2, alter_date="new")
    assert snapshot.metadata_hash(old, application=True) == snapshot.metadata_hash(
        updated, application=True
    )
    assert snapshot.metadata_hash(old, application=True) != snapshot.metadata_hash(
        dict(updated, proc_start="other"), application=True
    )


def test_workbench_component_replacement_checks_complete_final_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        snapshot, "observe_procedure", lambda *a: (RECORD, "verified-new")
    )
    deleted = selection(table="ii_components", action="d")
    inserted = selection(table="ii_components", action="i")
    candidate = AffectedSource(deleted.events + inserted.events, (12,), 102)
    inventory, _ = snapshot.refresh_procedures(
        SETTINGS, {"objects": {"app/probe": RECORD}}, candidate, {"app/probe": "before"}
    )
    assert inventory == {"app/probe": "verified-new"}


def test_scalar_integer_compile_classification_has_narrow_equivalence() -> None:
    row = {
        "data_type": "integer",
        "is_nullable": "N",
        "value_type": "      ",
        "value_string": "",
        "read_only": "N",
        "is_array": "N",
    }
    assert snapshot.metadata_hash(row, component=True) == snapshot.metadata_hash(
        dict(row, value_type="system"), component=True
    )
    assert snapshot.metadata_hash(row, component=True) != snapshot.metadata_hash(
        dict(row, value_type="user"), component=True
    )
    for changed in (
        {"data_type": "other"},
        {"is_nullable": "Y"},
        {"value_string": "42"},
        {"is_array": "Y"},
        {"read_only": "Y"},
    ):
        unusual = row | changed
        assert snapshot.metadata_hash(
            unusual, component=True
        ) != snapshot.metadata_hash(dict(unusual, value_type="system"), component=True)

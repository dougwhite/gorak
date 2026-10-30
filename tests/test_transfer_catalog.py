from unittest.mock import MagicMock

import pytest

from gorak import transfer_catalog as catalog
from gorak.connection import OpenRoadConnection
from gorak.database import ComponentSyncMetadata
from gorak.project import ProjectError


def test_inventory_preserves_identity_name_and_source_change_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = OpenRoadConnection("local", "node", "sample", None)
    monkeypatch.setattr(
        catalog,
        "application_tokens",
        lambda _: {"sample": {"id": 10, "name": "sample"}},
    )
    item = ComponentSyncMetadata(
        application_name="sample",
        component_name="renamed",
        entity_type="proc4glsource",
        base_entity_id=20,
        version_entity_id=21,
        version_number=-1,
        alter_date="2026-01-01",
        alter_count=3,
        last_altered_by="user",
        current_make=2,
    )
    monkeypatch.setattr(catalog, "read_all_component_sync_metadata", lambda _: [item])
    tokens = catalog.inventory(connection)
    assert tokens["sample/renamed"] == {
        "application_name": "sample",
        "component_name": "renamed",
        "entity_type": "proc4glsource",
        "base_entity_id": 20,
        "version_entity_id": 21,
        "version_number": -1,
        "alter_date": "2026-01-01",
        "alter_count": 3,
    }


def test_local_application_tokens_and_query_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gorak import local

    connection = OpenRoadConnection("local", "node", "sample", None)
    output = (
        "|application_name|entity_id|alter_date|alter_count|\n|sample|10|2026-01-01|3|"
    )
    run = MagicMock(return_value=output)
    monkeypatch.setattr(local, "run_subprocess", run)
    assert catalog.application_tokens(connection) == {
        "sample": {"name": "sample", "id": 10, "date": "2026-01-01", "count": 3}
    }
    assert "ii_applications" in run.call_args.args[1]
    run.return_value = "E_AD1012 Query failed"
    with pytest.raises(ProjectError, match="application change metadata"):
        catalog.application_tokens(connection)

from pathlib import Path

import pytest

from gorak.installation import (
    export_installation_sql,
    installation_sql,
    installation_statements,
)
from gorak.project import ProjectError


def test_rules_capture_both_identities_and_deletion_context() -> None:
    statements = installation_statements()
    rules = [s for s in statements if s.startswith("create rule")]
    assert len(rules) == 24
    update = next(s for s in rules if "after update on ii_entities" in s)
    for field in (
        "entity_id",
        "folder_id",
        "base_entity_id",
        "version_number",
        "entity_name",
        "entity_type",
    ):
        assert f"old.{field}" in update
        assert f"new.{field}" in update
    delete = next(s for s in rules if "after delete on ii_entities" in s)
    assert "p_old_object_name=old.entity_name" in delete
    assert "p_new_object_name=null" in delete
    insert = next(s for s in rules if "after insert on ii_srcobj_encoded" in s)
    assert "p_new_sequence_no=new.sequence_no" in insert
    assert "p_new_sub_type=new.sub_type" in insert
    assert "text_string" not in "\n".join(rules)


def test_export_preserves_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "install.sql"
    path.write_text("DBA edits")
    with pytest.raises(ProjectError, match="Refusing to overwrite"):
        export_installation_sql(path)
    assert path.read_text() == "DBA edits"


def test_script_is_fresh_capture_only_installation_with_error_stop() -> None:
    sql = installation_sql()
    assert "\\nocontinue" in sql
    assert "set session with on_error = rollback transaction" in sql
    assert "uuid_to_char(uuid_create())" in sql
    assert "'capture_only'" in sql
    statements = installation_statements()
    assert not any(
        s.startswith(("drop ", "grant ", "update ii_", "delete from ii_"))
        for s in statements
    )
    assert next(
        i
        for i, s in enumerate(statements)
        if s.startswith("insert into gorak_tracking_install")
    ) > max(i for i, s in enumerate(statements) if s.startswith("create rule"))


def test_upgrade_preserves_source_events_identity_and_rules() -> None:
    from gorak.installation import upgrade_statements

    statements = upgrade_statements()
    sql = "\n".join(statements)
    assert "primary key (consumer_id, event_id)" in sql
    assert "count(*) = 1 and min(schema_version) = 1" in sql
    assert "update gorak_tracking_install set schema_version = 2" in sql
    assert "uuid_create" not in sql
    assert not any(
        s.startswith(
            ("delete ", "create rule", "drop rule", "drop table gorak_change_events")
        )
        for s in statements
    )
    assert statements.index("commit") > next(
        i
        for i, s in enumerate(statements)
        if s.startswith("update gorak_tracking_install")
    )
    assert "Upgrade v1 to v2 only" in installation_sql(upgrade=True)

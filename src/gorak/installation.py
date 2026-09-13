"""Export a reviewable, capture-only Ingres hook installation script."""

from pathlib import Path

from .project import ProjectError

SCHEMA_VERSION = 1
# Preserve identity context at deletion time; values are trusted schema identifiers.
FIELDS: dict[str, str] = {
    "object_id": "integer",
    "parent_id": "integer",
    "base_id": "integer",
    "version_no": "integer",
    "sub_type": "integer",
    "sequence_no": "integer",
    "object_name": "varchar(32)",
    "object_type": "varchar(32)",
}
TABLES: dict[str, dict[str, str]] = {
    "ii_srcobj_encoded": {
        "object_id": "entity_id",
        "sub_type": "sub_type",
        "sequence_no": "sequence_no",
    },
    "ii_entities": {
        "object_id": "entity_id",
        "parent_id": "folder_id",
        "base_id": "base_entity_id",
        "version_no": "version_number",
        "object_name": "entity_name",
        "object_type": "entity_type",
    },
    "ii_components": {"object_id": "entity_id"},
    "ii_applications": {"object_id": "entity_id"},
    "ii_incl_apps": {
        "object_id": "app_id",
        "object_name": "incl_name",
        "version_no": "incl_version",
        "sequence_no": "incl_sequence",
    },
    "ii_stored_strings": {"object_id": "string_id", "sequence_no": "row_sequence"},
    "ii_stored_nstrings": {"object_id": "string_id", "sequence_no": "row_sequence"},
    "ii_stored_bitmaps": {"object_id": "picture_id", "sequence_no": "row_sequence"},
}


def installation_statements() -> list[str]:
    columns = [
        f"{side}_{name} {kind}"
        for side in ("old", "new")
        for name, kind in FIELDS.items()
    ]
    parameters = [f"p_{column}" for column in columns]
    values = [f":p_{side}_{name}" for side in ("old", "new") for name in FIELDS]
    statements = [
        "set autocommit off",
        "set session with on_error = rollback transaction",
        "create table gorak_tracking_install (schema_version integer not null, installation_id char(36) not null, mode varchar(32) not null) with page_size=8192",
        "create table gorak_change_events (event_id bigint not null, source_table varchar(32) not null, action char(1) not null, "
        + ", ".join(columns)
        + ") with page_size=8192",
        "modify gorak_change_events to btree on event_id",
        "create sequence gorak_change_seq as bigint start with 1 increment by 1",
        "create procedure gorak_record_change(p_table varchar(32), p_action char(1), "
        + ", ".join(parameters)
        + ") as begin\n    insert into gorak_change_events values (next value for gorak_change_seq, :p_table, :p_action, "
        + ", ".join(values)
        + ");\nend",
    ]
    for index, (table, mapping) in enumerate(TABLES.items()):
        for action, code in (("insert", "i"), ("update", "u"), ("delete", "d")):
            args = [f"p_table='{table}'", f"p_action='{code}'"]
            for side in ("old", "new"):
                present = not (
                    (side == "old" and action == "insert")
                    or (side == "new" and action == "delete")
                )
                for name in FIELDS:
                    value = (
                        f"{side}.{mapping[name]}"
                        if present and name in mapping
                        else "null"
                    )
                    args.append(f"p_{side}_{name}={value}")
            statements.append(
                f"create rule gorak_track_{index}_{code} after {action} on {table}\n    execute procedure gorak_record_change("
                + ", ".join(args)
                + ")"
            )
    statements += [
        f"insert into gorak_tracking_install values ({SCHEMA_VERSION}, uuid_to_char(uuid_create()), 'capture_only')",
        "commit",
        "select schema_version, installation_id, mode from gorak_tracking_install",
    ]
    return statements


def installation_sql() -> str:
    header = """-- Gorak capture-only tracking schema v1, for DBA review.
-- Run ONLY in an initialized OpenROAD source database as its $ingres owner.
-- Ingres terminal-monitor script, not a database-creation or migration script.
-- Set II_TM_EXIT_ON_ERROR=rollback in the invoking environment.
-- Example: II_TM_EXIT_ON_ERROR=rollback sql '-u$ingres' source_db < gorak-install.sql
-- Stop on any error; never infer success from the process exit code alone.
-- Fresh installation only: existing Gorak names cause failure; nothing is dropped.
-- No grants are issued. DBA controls read access; developers need no owner login.
-- Capture only: no fast-sync consumer, pruning, upgrades, or full coverage guarantee.
-- Events grow until an explicit retention mechanism is implemented.
-- Validate in a disposable database before deployment. See docs/installation.md.
\\nocontinue
"""
    return header + "\n".join(
        statement + ";\n\\g\n" for statement in installation_statements()
    )


def export_installation_sql(path: Path) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(installation_sql())
    except FileExistsError as ex:
        raise ProjectError(f"Refusing to overwrite existing SQL file: {path}") from ex

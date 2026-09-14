"""DBA-reviewed experimental revision extension for an existing v2 journal."""

from pathlib import Path

from .errors import ProjectError

REVISION_TABLE = "gorak_revision_lanes"


def revision_installation_statements() -> list[str]:
    """Fresh extension only; preserve parent capture definitions and event history."""
    return [
        "set autocommit off",
        "set session with on_error = rollback transaction",
        "create table gorak_revision_guard (valid integer not null check(valid=1))",
        "insert into gorak_revision_guard select case when count(*)=1 and min(schema_version)=2 and min(mode)='capture_only' then 1 else 0 end from gorak_tracking_install",
        "create table gorak_revision_install (schema_version integer not null, revision_id char(36) not null, parent_installation_id char(36) not null) with page_size=8192",
        f"create table {REVISION_TABLE} (server_id varchar(64) not null, session_id varchar(64) not null, revision bigint not null check(revision>0), primary key(server_id,session_id)) with page_size=8192",
        f"modify {REVISION_TABLE} to btree on server_id,session_id",
        "create procedure gorak_bump_revision() as begin\n"
        f"    update {REVISION_TABLE} set revision=revision+1 where server_id=dbmsinfo('ima_server') and session_id=dbmsinfo('session_id');\n"
        "    if iirowcount=0 then\n"
        f"        insert into {REVISION_TABLE} values(dbmsinfo('ima_server'),dbmsinfo('session_id'),1);\n"
        "    endif;\nend",
        "create rule gorak_revision_capture after insert on gorak_change_events execute procedure gorak_bump_revision",
        "insert into gorak_revision_install select 1,uuid_to_char(uuid_create()),installation_id from gorak_tracking_install",
        "drop table gorak_revision_guard",
        "commit",
        "select schema_version,revision_id,parent_installation_id from gorak_revision_install",
    ]


def revision_installation_sql() -> str:
    return """-- Gorak experimental revision extension v1: DBA review required.
-- Fresh extension of an existing capture-only journal v2, as $ingres owner.
-- Stop source writers for installation and configuration. Do not deploy to
-- unconfigured clients: revision writers AND readers need table-specific
-- MVCC/shared on gorak_revision_lanes. Keep application isolation unchanged.
-- Initial research scope: one DBMS server. Multi-server/restart certification,
-- restore generations, retention and fast status are not provided by this script.
-- Configure clients before resuming writes. No grants are issued here.
-- Developers need SELECT on gorak_revision_install and gorak_revision_lanes;
-- do not grant direct counter mutation. Existing source permissions stay unchanged.
-- Existing names abort: no objects are replaced and no source data is rewritten.
-- Stop on any error. Run with II_TM_EXIT_ON_ERROR=rollback; inspect SQL diagnostics.
-- Counters start at installation, not at the beginning of retained event history.
-- Keep full comparison enabled. See docs/research/revision-extension.md.
\\nocontinue
""" + "\n".join(s + ";\n\\g\n" for s in revision_installation_statements())


def export_revision_installation_sql(path: Path) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(revision_installation_sql())
    except FileExistsError as ex:
        raise ProjectError(f"Refusing to overwrite existing SQL file: {path}") from ex


def revision_reset_statements() -> list[str]:
    """Offline DBA generation rotation; never use while source writers are active."""
    return [
        "set autocommit off",
        "set session with on_error = rollback transaction",
        "create table gorak_revision_reset_guard (valid integer not null check(valid=1))",
        "insert into gorak_revision_reset_guard select case when count(*)=1 and min(r.schema_version)=1 and min(p.schema_version)=2 and min(p.mode)='capture_only' and min(r.parent_installation_id)=min(p.installation_id) then 1 else 0 end from gorak_revision_install r cross join gorak_tracking_install p",
        "update gorak_revision_install set revision_id=uuid_to_char(uuid_create())",
        "delete from gorak_revision_lanes",
        "drop table gorak_revision_reset_guard",
        "commit",
        "select revision_id from gorak_revision_install",
    ]


def revision_reset_sql() -> str:
    return (
        "-- Gorak OFFLINE revision generation reset, run as $ingres.\n"
        "-- Stop and drain ALL source writers before executing.\n"
        "-- Required AFTER database restore, DBMS restart, hook changes, or lane maintenance\n"
        "-- and BEFORE permitting source clients to reconnect. Do not run online.\n"
        "-- Configure clients with the NEW generation; old checkpoints cannot be reused.\n"
        "-- Source and journal history are preserved. Counter lanes are cleared.\n"
        "-- Use II_TM_EXIT_ON_ERROR=rollback; stop on errors.\n\\nocontinue\n"
        + "\n".join(s + ";\n\\g\n" for s in revision_reset_statements())
    )


def export_revision_reset_sql(path: Path) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(revision_reset_sql())
    except FileExistsError:
        raise ProjectError(f"Refusing to overwrite existing SQL file: {path}") from None

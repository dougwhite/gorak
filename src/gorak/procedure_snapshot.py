"""Oracle-bound, conservative procedure observations for managed dirty refresh."""

import hashlib
import json
from typing import Any

from sqlalchemy import text

from .affected_source import MAX_OBJECTS, AffectedSource
from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .encoded_source import UnsupportedSource, read_procedure
from .importer import signature
from .sync_plan import semantic_hashes

IDENTITIES_SQL = f"""
select first {MAX_OBJECTS + 1} ver.entity_id,base.entity_id,ver.entity_name,app.entity_id,app.base_entity_id
from "$ingres".ii_entities ver
join "$ingres".ii_entities base on ver.base_entity_id=base.entity_id
join "$ingres".ii_entities app on base.folder_id=app.base_entity_id
join "$ingres".ii_applications a on a.entity_id=app.entity_id
where ver.version_number=-1 and app.version_number=-1
and base.base_entity_id=0 and ver.entity_type='proc4glsource'
and lower(app.entity_name)=:app
"""


def entity_row(
    connection: Any,
    identity: int,
    *,
    component: bool = False,
    application: bool = False,
) -> dict[str, Any]:
    table = (
        "ii_applications"
        if application
        else "ii_components"
        if component
        else "ii_entities"
    )
    result = connection.execute(
        text(f'select first 2 * from "$ingres".{table} where entity_id=:identity'),
        {"identity": identity},
    )
    try:
        names = list(result.keys())
        rows = result.fetchmany(2)
    finally:
        result.close()
    if len(rows) != 1 or len(set(names)) != len(names):
        raise UnsupportedSource("missing_or_ambiguous_entity")
    return dict(zip(names, rows[0], strict=True))


def metadata_hash(
    row: dict[str, Any],
    *,
    version: bool = False,
    component: bool = False,
    application: bool = False,
) -> str:
    # Protect every column, including unfamiliar metadata. Only the version remark
    # is decoded separately; known alteration/compile bookkeeping is nonsemantic.
    # Other destination-local changes conservatively force XML.
    ignored = {"short_remark"} if version else set()
    if component or application:
        ignored = {"last_altered_by", "alter_date", "alter_count"}
    if component:
        ignored.add("current_make")
    if (
        component
        and row.get("data_type") == "integer"
        and row.get("is_nullable") == "N"
        and row.get("value_string") == ""
        and row.get("read_only") == "N"
        and row.get("is_array") == "N"
        and isinstance(row.get("value_type"), str)
        and row["value_type"].strip() in {"", "system"}
    ):
        # CLI compilation fills this derived classification for the supported
        # scalar integer form. Other types, defaults and classifications are guarded.
        row = dict(row, value_type="system")
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in row.items() if k not in ignored},
            sort_keys=True,
            ensure_ascii=True,
            default=str,
        ).encode("ascii")
    ).hexdigest()


def observe_procedure(
    settings: OdbcSettings,
    identity: int,
    base_id: int,
    engine_factory: EngineFactory = create_odbc_engine,
) -> tuple[dict[str, Any], str]:
    engine = engine_factory(settings)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "set lockmode session where level=mvcc, readlock=shared, timeout=5"
                )
            )
            version = entity_row(connection, identity)
            base = entity_row(connection, base_id)
            component = entity_row(connection, identity, component=True)
        if (
            version["entity_id"] != identity
            or version["base_entity_id"] != base_id
            or version["version_number"] != -1
            or base["base_entity_id"] != 0
            or version["folder_id"] != base["folder_id"]
            or str(version["entity_type"]).strip() != "proc4glsource"
            or str(base["entity_type"]).strip() != "proc4glsource"
            or str(version["entity_name"]).casefold()
            != str(base["entity_name"]).casefold()
        ):
            raise UnsupportedSource("unsupported_procedure_identity")
        name = version["entity_name"]
        description = version["short_remark"]
        if not isinstance(name, str) or not isinstance(description, str):
            raise UnsupportedSource("invalid_procedure_metadata")
        source = read_procedure(settings, identity, engine_factory)
        digest = semantic_hashes(
            {"component": signature(source.component(name, description))}
        )["component"]
        return {
            "identity": identity,
            "base_id": base_id,
            "version_metadata": metadata_hash(version, version=True),
            "base_metadata": metadata_hash(base),
            "component_metadata": metadata_hash(component, component=True),
        }, digest
    finally:
        engine.dispose()


def observe_application(
    settings: OdbcSettings,
    identity: int,
    base_id: int,
    engine_factory: EngineFactory = create_odbc_engine,
) -> dict[str, Any]:
    engine = engine_factory(settings)
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "set lockmode session where level=mvcc, readlock=shared, timeout=5"
                )
            )
            version = entity_row(connection, identity)
            base = entity_row(connection, base_id)
            application = entity_row(connection, identity, application=True)
        if (
            version["base_entity_id"] != base_id
            or version["version_number"] != -1
            or base["base_entity_id"] != 0
            or str(version["entity_type"]).strip() != "appsource"
            or str(base["entity_type"]).strip() != "appsource"
        ):
            raise UnsupportedSource("unsupported_application_identity")
        return {
            "identity": identity,
            "base_id": base_id,
            "version_metadata": metadata_hash(version),
            "base_metadata": metadata_hash(base),
            "application_metadata": metadata_hash(application, application=True),
        }
    finally:
        engine.dispose()


def bootstrap_procedures(
    settings: OdbcSettings,
    scope: list[str],
    inventory: dict[str, str],
    engine_factory: EngineFactory = create_odbc_engine,
) -> dict[str, Any]:
    """Enroll only procedures whose entire decoded XML signature equals the oracle."""
    engine = engine_factory(settings)
    objects: dict[str, Any] = {}
    try:
        with engine.connect() as connection:
            connection.execute(
                text(
                    "set lockmode session where level=mvcc, readlock=shared, timeout=5"
                )
            )
            maximum = connection.execute(
                text('select max(event_id) from "$ingres".gorak_change_events')
            ).scalar()
            if maximum is None:
                maximum = 0
            if type(maximum) is not int or maximum < 0:
                raise UnsupportedSource("invalid_event_maximum")
            identities: list[tuple[str, int, int]] = []
            app_ids: dict[str, tuple[int, int]] = {}
            for app in scope:
                result = connection.execute(text(IDENTITIES_SQL), {"app": app})
                try:
                    rows = result.fetchmany(MAX_OBJECTS + 1)
                finally:
                    result.close()
                if len(identities) + len(rows) > MAX_OBJECTS:
                    return {"maximum": maximum, "objects": {}}
                for identity, base, name, app_id, app_base in rows:
                    if (
                        type(identity) is not int
                        or type(base) is not int
                        or not isinstance(name, str)
                        or type(app_id) is not int
                        or type(app_base) is not int
                    ):
                        raise UnsupportedSource("invalid_procedure_identity")
                    if app in app_ids and app_ids[app] != (app_id, app_base):
                        raise UnsupportedSource("ambiguous_application_identity")
                    app_ids[app] = (app_id, app_base)
                    identities.append((f"{app}/{name}".casefold(), identity, base))
        seen: set[str] = set()
        for key, identity, base in identities:
            if key in seen:
                raise UnsupportedSource("ambiguous_procedure_identity")
            seen.add(key)
            try:
                record, digest = observe_procedure(
                    settings, identity, base, engine_factory
                )
            except UnsupportedSource:
                continue
            if inventory.get(key) == digest:
                objects[key] = record
        applications = {
            app: observe_application(settings, *ids, engine_factory)
            for app, ids in app_ids.items()
            if any(key.startswith(app + "/") for key in objects)
        }
        return {"maximum": maximum, "objects": objects, "applications": applications}
    finally:
        engine.dispose()


def refresh_procedures(
    settings: OdbcSettings,
    snapshot: dict[str, Any],
    selection: AffectedSource,
    inventory: dict[str, str],
    engine_factory: EngineFactory = create_odbc_engine,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Return an all-or-nothing candidate refresh; no mutation of previous evidence."""
    if selection.fallback:
        raise UnsupportedSource(selection.fallback)
    records = snapshot["objects"]
    applications = snapshot.get("applications", {})
    lookup: dict[int, str] = {}
    for key, record in (records | applications).items():
        for identity in (record["identity"], record["base_id"]):
            if identity in lookup:
                raise UnsupportedSource("ambiguous_cached_identity")
            lookup[identity] = key
    if any(identity not in lookup for identity in selection.object_ids):
        raise UnsupportedSource("unresolved_or_unsupported_affected_object")
    for event in selection.events:
        ids = {
            value
            for side in (event.old, event.new)
            if type(value := side.get("object_id")) is int
        }
        app_event = any(lookup[identity] in applications for identity in ids)
        allowed = (
            {"ii_entities", "ii_applications"}
            if app_event
            else {"ii_entities", "ii_components", "ii_srcobj_encoded"}
        )
        if event.source_table not in allowed:
            raise UnsupportedSource("unsupported_affected_table")
        if (
            event.source_table in {"ii_entities", "ii_applications"}
            and event.action != "u"
        ):
            raise UnsupportedSource("identity_creation_or_deletion_requires_xml")
    updated = dict(inventory)
    for key in sorted({lookup[identity] for identity in selection.object_ids}):
        if key in applications:
            old = applications[key]
            if (
                observe_application(
                    settings, old["identity"], old["base_id"], engine_factory
                )
                != old
            ):
                raise UnsupportedSource("application_identity_or_metadata_changed")
        else:
            old = records[key]
            current, digest = observe_procedure(
                settings, old["identity"], old["base_id"], engine_factory
            )
            if current != old:
                raise UnsupportedSource("procedure_identity_or_metadata_changed")
            updated[key] = digest
    return updated, {
        "maximum": selection.maximum,
        "objects": records,
        "applications": applications,
    }

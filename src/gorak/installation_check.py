"""Read-only installation inventory; never authorizes incremental sync."""

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import text

from .database import EngineFactory, OdbcSettings, create_odbc_engine
from .installation import SCHEMA_VERSION, TABLES
from .installation_definitions import definition_issues
from .installation_schema import column_issues

# Owner filtering prevents a same-named developer object from satisfying a check.
CATALOG_QUERIES = {
    "tables": "select table_name from iitables where table_owner = '$ingres' and table_type = 'T'",
    "rules": "select distinct rule_name, table_name from iirules where rule_owner = '$ingres'",
    "procedures": "select distinct procedure_name from iiprocedures where procedure_owner = '$ingres'",
    "sequences": "select seq_name from iisequences where seq_owner = '$ingres'",
}
EXPECTED_TABLES = {"gorak_tracking_install", "gorak_change_events"}
EXPECTED_RULES = {
    f"gorak_track_{index}_{action}": table
    for index, table in enumerate(TABLES)
    for action in ("i", "u", "d")
}


@dataclass(frozen=True)
class InstallationCheck:
    status: str
    installation_id: str | None
    issues: list[str]
    incremental_ready: bool = False
    tracking_objects_present: bool = True
    schema_version: int | None = None
    definitions_verified: bool = False
    columns_verified: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def check_installation(
    settings: OdbcSettings,
    engine_factory: EngineFactory = create_odbc_engine,
) -> InstallationCheck:
    """Inspect catalog inventory and marker without reading source or event payloads."""
    engine = engine_factory(settings)
    issues: list[str] = []
    installation_id = None
    schema_version = None
    try:
        with engine.connect() as connection:
            # Bounded waiting; do not inherit a site's dirty-read configuration.
            connection.execute(
                text("set lockmode session where readlock = shared, timeout = 5")
            )
            inventory = {
                kind: {str(row[0]).strip() for row in connection.execute(text(query))}
                for kind, query in CATALOG_QUERIES.items()
                if kind != "rules"
            }
            rules = {
                (str(row[0]).strip(), str(row[1]).strip())
                for row in connection.execute(text(CATALOG_QUERIES["rules"]))
            }
            for kind, expected in (
                ("tables", EXPECTED_TABLES),
                ("procedures", {"gorak_record_change"}),
                ("sequences", {"gorak_change_seq"}),
            ):
                issues.extend(
                    f"Missing owner {kind}: {name}"
                    for name in sorted(expected - inventory[kind])
                )
            for rule, table in EXPECTED_RULES.items():
                if (rule, table) not in rules:
                    issues.append(
                        f"Missing or wrong-target owner rule: {rule} on {table}"
                    )
            if "gorak_tracking_install" in inventory["tables"]:
                rows = list(
                    connection.execute(
                        text(
                            "select schema_version, installation_id, mode "
                            'from "$ingres".gorak_tracking_install'
                        )
                    )
                )
                if len(rows) != 1:
                    issues.append("Expected exactly one installation record")
                else:
                    version, identity, mode = rows[0]
                    schema_version = int(version)
                    if version not in (1, SCHEMA_VERSION):
                        issues.append(f"Unsupported tracking schema version: {version}")
                    if str(mode).strip() != "capture_only":
                        issues.append("Unsupported tracking mode")
                    try:
                        parsed = UUID(str(identity).strip())
                        if parsed.int == 0:
                            raise ValueError
                        installation_id = str(parsed)
                    except ValueError:
                        issues.append("Invalid installation UUID")
            if schema_version == 2:
                if "gorak_journal_acks" not in inventory["tables"]:
                    issues.append("Missing owner tables: gorak_journal_acks")
                else:
                    connection.execute(
                        text(
                            'select consumer_id, event_id from "$ingres".gorak_journal_acks where 1 = 0'
                        )
                    )
            columns = column_issues(connection, inventory["tables"])
            issues.extend(columns)
            required_tables = EXPECTED_TABLES | (
                {"gorak_journal_acks"} if schema_version == 2 else set()
            )
            columns_verified = required_tables <= inventory["tables"] and not columns
            present_rules = {name for name, _ in rules} & EXPECTED_RULES.keys()
            procedure_present = "gorak_record_change" in inventory["procedures"]
            definitions = definition_issues(
                connection, present_rules, procedure_present
            )
            issues.extend(definitions)
            definitions_verified = (
                present_rules == EXPECTED_RULES.keys()
                and procedure_present
                and not definitions
            )
            # Verify developer read permission without scanning accumulated events.
            if "gorak_change_events" in inventory["tables"]:
                connection.execute(
                    text(
                        'select event_id from "$ingres".gorak_change_events where 1 = 0'
                    )
                )
    finally:
        engine.dispose()
    return InstallationCheck(
        "incomplete" if issues else "capture_only_inventory_present",
        installation_id,
        issues,
        schema_version=schema_version,
        definitions_verified=definitions_verified,
        columns_verified=columns_verified,
        tracking_objects_present=bool(
            inventory["tables"]
            & (EXPECTED_TABLES | {"gorak_journal_acks", "gorak_upgrade_guard"})
            or inventory["procedures"] & {"gorak_record_change"}
            or inventory["sequences"] & {"gorak_change_seq"}
            or {name for name, _ in rules} & EXPECTED_RULES.keys()
        ),
    )

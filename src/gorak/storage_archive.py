"""Validated table archives for isolated direct-reconstruction experiments.

This format preserves source rows, including opaque framed graphs. It does not
certify arbitrary class semantics and is not wired into normal import or sync.
Database mutation requires a separate transaction/target/concurrency protocol.
"""

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from .encoded_graph import UnsupportedSource
from .storage_graph import decode, encode

type Value = str | int | None
type Row = dict[str, Value]
TABLE_COLUMNS = {
    "ii_entities": "entity_id folder_id base_entity_id entity_type entity_name branch_name version_number partition_name qual_ind instance_level added_by create_date short_remark entity_origin implement_lock system_lock",
    "ii_components": "entity_id last_altered_by alter_date alter_count data_type is_nullable current_make change_type value_type value_string read_only is_array",
    "ii_applications": "entity_id last_altered_by alter_date alter_count database_name proc_start command_line init_procedure exit_procedure timeout_procedure timeout_seconds major_version minor_version",
    "ii_incl_apps": "app_id incl_name incl_version incl_filename incl_sequence",
    "ii_srcobj_encoded": "entity_id sub_type sequence_no text_string",
    "ii_longremarks": "object_id remark_sequence long_remark remark_language",
    "ii_dependencies": "src_entity_id src_entity_type rel_class_type dest_entity_id dest_app_name dest_comp_name qualified_ref dependency_origin",
    "ii_app_cntns_comp": "app_id comp_id comp_type",
}
REFERENCES = {
    "ii_entities": {"entity_id", "folder_id", "base_entity_id"},
    "ii_components": {"entity_id"},
    "ii_applications": {"entity_id"},
    "ii_incl_apps": {"app_id"},
    "ii_srcobj_encoded": {"entity_id"},
    "ii_longremarks": {"object_id"},
    "ii_dependencies": {"src_entity_id", "dest_entity_id"},
    "ii_app_cntns_comp": {"app_id", "comp_id"},
}
INTEGER_COLUMNS = {
    "ii_entities": {"entity_id", "folder_id", "base_entity_id", "version_number"},
    "ii_components": {"entity_id", "alter_count", "current_make", "change_type"},
    "ii_applications": {
        "entity_id",
        "alter_count",
        "timeout_seconds",
        "major_version",
        "minor_version",
    },
    "ii_incl_apps": {"app_id", "incl_version", "incl_sequence"},
    "ii_srcobj_encoded": {"entity_id", "sub_type", "sequence_no"},
    "ii_longremarks": {"object_id", "remark_sequence"},
    "ii_dependencies": {"src_entity_id", "dest_entity_id"},
    "ii_app_cntns_comp": {"app_id", "comp_id"},
}
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_ROWS = 200_000


def sql_literal(value: Value) -> str:
    """Exact ASCII text for the Ingres monitor, which strips literal newlines.

    Hex also prevents source text from injecting monitor commands or SQL syntax.
    Normal parameterized DBAPI writers do not need this transport encoding.
    """
    if value is None:
        return "null"
    if type(value) is int and -(2**31) <= value < 2**31:
        return str(value)
    if isinstance(value, str) and value.isascii() and "\x00" not in value:
        return "varchar(X'" + value.encode("ascii").hex() + "')" if value else "''"
    raise UnsupportedSource("unsupported_archive_scalar")


def _integer(value: Value) -> int:
    if type(value) is not int or not 0 <= value < 2**31:
        raise UnsupportedSource("invalid_archive_identity")
    return value


@dataclass(frozen=True)
class Archive:
    # Public input is copied and revalidated by every serialization/remapping call.
    tables: Mapping[str, list[Row]]

    def validate(self) -> None:
        if set(self.tables) != set(TABLE_COLUMNS):
            raise UnsupportedSource("incomplete_or_unknown_archive_tables")
        total = 0
        size = 0
        for table, rows in self.tables.items():
            total += len(rows)
            if total > MAX_ROWS:
                raise UnsupportedSource("archive_row_budget_exceeded")
            columns = set(TABLE_COLUMNS[table].split())
            for row in rows:
                if set(row) != columns:
                    raise UnsupportedSource("unsupported_archive_columns")
                for column, value in row.items():
                    if column in INTEGER_COLUMNS[table]:
                        if type(value) is not int:
                            raise UnsupportedSource("invalid_archive_column_type")
                    elif value is not None and not isinstance(value, str):
                        raise UnsupportedSource("invalid_archive_column_type")
                    size += len(value) if isinstance(value, str) else 4
                    if size > MAX_ARCHIVE:
                        raise UnsupportedSource("archive_size_budget_exceeded")
                    sql_literal(value)  # Type/range/encoding gate, not output.
        entities = self.tables["ii_entities"]
        ids = {_integer(row["entity_id"]) for row in entities}
        if not ids or 0 in ids or len(ids) != len(entities):
            raise UnsupportedSource("duplicate_or_missing_archive_entity")
        for table, rows in self.tables.items():
            for row in rows:
                for column in REFERENCES[table]:
                    value = _integer(row[column])
                    if value and value not in ids:
                        raise UnsupportedSource("external_archive_identity_unresolved")
        versions = {_integer(row["entity_id"]): row for row in entities}
        for row in entities:
            name = row["entity_name"]
            if not isinstance(name, str) or not name:
                raise UnsupportedSource("invalid_archive_entity_name")
            base = _integer(row["base_entity_id"])
            folder = _integer(row["folder_id"])
            if base:
                parent = versions[base]
                parent_name = parent["entity_name"]
                if (
                    not isinstance(parent_name, str)
                    or parent_name.casefold() != name.casefold()
                    or parent["base_entity_id"] != 0
                    or parent["entity_type"] != row["entity_type"]
                    or parent["folder_id"] != row["folder_id"]
                    or row["version_number"] != -1
                ):
                    raise UnsupportedSource("unsupported_archive_version_relationship")
            elif row["version_number"] != 0:
                raise UnsupportedSource("unsupported_archive_base_version")
            if folder and (
                versions[folder]["entity_type"] != "appsource"
                or versions[folder]["base_entity_id"] != 0
            ):
                raise UnsupportedSource("invalid_archive_application_folder")
        current = {
            identity: row
            for identity, row in versions.items()
            if row["base_entity_id"] != 0
        }
        bases = [row["base_entity_id"] for row in current.values()]
        if len(set(bases)) != len(bases) or set(bases) != set(versions) - set(current):
            raise UnsupportedSource("incomplete_or_duplicate_archive_current_version")
        for table, expected in [
            (
                "ii_applications",
                {i for i, r in current.items() if r["entity_type"] == "appsource"},
            ),
            (
                "ii_components",
                {i for i, r in current.items() if r["entity_type"] != "appsource"},
            ),
        ]:
            actual = [_integer(row["entity_id"]) for row in self.tables[table]]
            if set(actual) != expected or len(actual) != len(expected):
                raise UnsupportedSource("incomplete_or_duplicate_archive_metadata")
        app_ids = {_integer(row["entity_id"]) for row in self.tables["ii_applications"]}
        include_keys: set[tuple[int, int]] = set()
        for row in self.tables["ii_incl_apps"]:
            key = _integer(row["app_id"]), _integer(row["incl_sequence"])
            if key[0] not in app_ids or key in include_keys:
                raise UnsupportedSource("invalid_archive_include_owner_or_order")
            include_keys.add(key)
        self._validate_payloads(current)

    def _validate_payloads(self, current: Mapping[int, Row]) -> None:
        grouped: dict[int, dict[int, str]] = defaultdict(dict)
        for row in self.tables["ii_srcobj_encoded"]:
            identity = _integer(row["entity_id"])
            sequence = _integer(row["sequence_no"])
            value = row["text_string"]
            if (
                type(row["sub_type"]) is not int
                or row["sub_type"] != 1
                or not isinstance(value, str)
                or not 1 <= len(value) <= 1790
                or sequence in grouped[identity]
            ):
                raise UnsupportedSource("invalid_archive_source_chunk")
            grouped[identity][sequence] = value
        graph_kinds = {
            "appsource",
            "classsource",
            "framesource",
            "proc4glsource",
            "proc3glsource",
            "scriptsource",
            "ghostsource",
        }
        scalar_kinds = {"globsource", "constsource"}
        if any(
            row["entity_type"] not in graph_kinds | scalar_kinds
            for row in current.values()
        ):
            raise UnsupportedSource("unsupported_archive_component_kind")
        expected = {
            i for i, row in current.items() if row["entity_type"] in graph_kinds
        }
        if set(grouped) != expected:
            raise UnsupportedSource("missing_or_unexpected_archive_source_graph")
        for identity, chunks in grouped.items():
            if set(chunks) != set(range(len(chunks))):
                raise UnsupportedSource("missing_archive_source_chunk")
            payload = "".join(chunks[i] for i in range(len(chunks)))
            graph = decode(payload)
            kind = current[identity]["entity_type"]
            assert isinstance(kind, str)
            expected_kinds = (
                {"appsource", "imgappsource"} if kind == "appsource" else {kind}
            )
            if graph.records[0].kind not in expected_kinds:
                raise UnsupportedSource("archive_source_graph_kind_mismatch")
            if encode(graph) != payload:
                raise UnsupportedSource("archive_graph_roundtrip_mismatch")

    def dumps(self) -> str:
        self.validate()
        tables = {
            table: sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
            for table, rows in self.tables.items()
        }
        result = (
            json.dumps({"format": 1, "tables": tables}, sort_keys=True, indent=2) + "\n"
        )
        if len(result) > MAX_ARCHIVE:
            raise UnsupportedSource("archive_size_budget_exceeded")
        return result

    def remap(self, identities: Mapping[int, int]) -> "Archive":
        """Remap catalog references only; graph-local identities remain unchanged."""
        self.validate()
        ids = {_integer(row["entity_id"]) for row in self.tables["ii_entities"]}
        if (
            set(identities) != ids
            or any(type(key) is not int for key in identities)
            or any(_integer(value) == 0 for value in identities.values())
            or len(set(identities.values())) != len(ids)
        ):
            raise UnsupportedSource("invalid_archive_identity_mapping")
        tables: dict[str, list[Row]] = {}
        for table, rows in self.tables.items():
            tables[table] = []
            for row in rows:
                copied = dict(row)
                for key in REFERENCES[table]:
                    value = _integer(row[key])
                    if value:
                        copied[key] = identities[value]
                tables[table].append(copied)
        result = Archive(tables)
        result.validate()
        return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise UnsupportedSource("duplicate_archive_json_key")
        result[key] = value
    return result


def loads(value: str) -> Archive:
    if len(value) > MAX_ARCHIVE:
        raise UnsupportedSource("archive_size_budget_exceeded")
    try:
        raw = json.loads(value, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as exc:
        raise UnsupportedSource("invalid_archive_json") from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"format", "tables"}
        or type(raw["format"]) is not int
        or raw["format"] != 1
        or not isinstance(raw["tables"], dict)
    ):
        raise UnsupportedSource("unsupported_archive_format")
    tables: dict[str, list[Row]] = {}
    for table, rows in raw["tables"].items():
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise UnsupportedSource("invalid_archive_rows")
        tables[table] = rows
    archive = Archive(tables)
    archive.validate()
    return archive

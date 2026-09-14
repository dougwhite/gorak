import json
from copy import deepcopy
from pathlib import Path

import pytest

from gorak.encoded_graph import UnsupportedSource
from gorak.storage_archive import (
    INTEGER_COLUMNS,
    TABLE_COLUMNS,
    Archive,
    Row,
    loads,
    sql_literal,
)


def archive() -> Archive:
    tables: dict[str, list[Row]] = {table: [] for table in TABLE_COLUMNS}

    def row(table: str, **values: str | int | None) -> Row:
        value: Row = {
            key: 0 if key in INTEGER_COLUMNS[table] else ""
            for key in TABLE_COLUMNS[table].split()
        }
        value.update(values)
        tables[table].append(value)
        return value

    for identity, folder, base, version, kind, name in [
        (1, 0, 0, 0, "appsource", "sample"),
        (2, 0, 1, -1, "appsource", "sample"),
        (3, 1, 0, 0, "proc4glsource", "probe"),
        (4, 1, 3, -1, "proc4glsource", "probe"),
    ]:
        row(
            "ii_entities",
            entity_id=identity,
            folder_id=folder,
            base_entity_id=base,
            version_number=version,
            entity_type=kind,
            entity_name=name,
        )
    row("ii_applications", entity_id=2)
    row("ii_components", entity_id=4)
    row(
        "ii_incl_apps",
        app_id=2,
        incl_name="core",
        incl_sequence=0,
        incl_version=-1,
        incl_filename="core.plb",
    )
    chunks = json.loads(
        (Path(__file__).parent / "fixtures/encoded_source/initial.json").read_text()
    )
    for subtype, sequence, value in chunks:
        row(
            "ii_srcobj_encoded",
            entity_id=4,
            sub_type=subtype,
            sequence_no=sequence,
            text_string=value,
        )
    row(
        "ii_srcobj_encoded",
        entity_id=2,
        sub_type=1,
        sequence_no=0,
        text_string="1\n14: Source Object\n1\n\n9:appsource\n1\n1\n\n0\n\n$\n=\n",
    )
    return Archive(tables)


def test_serialization_roundtrip_is_stable_and_independent_of_original() -> None:
    original = archive()
    encoded = original.dumps()
    restored = loads(encoded)
    assert restored.dumps() == original.dumps()
    assert restored.dumps() == encoded
    restored.tables["ii_entities"][0]["short_remark"] = "edited"
    assert original.tables["ii_entities"][0]["short_remark"] == ""


def test_remaps_all_catalog_relationships_without_touching_graph_ids() -> None:
    original = archive()
    restored = original.remap({1: 101, 2: 102, 3: 103, 4: 104})
    assert restored.tables["ii_entities"][3]["base_entity_id"] == 103
    assert restored.tables["ii_entities"][3]["folder_id"] == 101
    assert restored.tables["ii_incl_apps"][0]["app_id"] == 102
    assert restored.tables["ii_components"][0]["entity_id"] == 104
    assert (
        restored.tables["ii_srcobj_encoded"][0]["text_string"]
        == original.tables["ii_srcobj_encoded"][0]["text_string"]
    )
    assert original.tables["ii_entities"][0]["entity_id"] == 1


@pytest.mark.parametrize(
    "mapping",
    [
        {1: 5},
        {1: 5, 2: 5, 3: 6, 4: 7},
        {1: 0, 2: 6, 3: 7, 4: 8},
        {1: -1, 2: 6, 3: 7, 4: 8},
        {1: True, 2: 6, 3: 7, 4: 8},
    ],
)
def test_rejects_incomplete_or_colliding_identity_mapping(
    mapping: dict[int, int],
) -> None:
    with pytest.raises(UnsupportedSource):
        archive().remap(mapping)


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("ii_entities", "folder_id", 999),
        ("ii_entities", "entity_id", True),
        ("ii_entities", "base_entity_id", "1"),
        ("ii_entities", "version_number", 8),
        ("ii_incl_apps", "app_id", 999),
        ("ii_srcobj_encoded", "sequence_no", 1),
        ("ii_srcobj_encoded", "sub_type", 2),
        ("ii_srcobj_encoded", "text_string", "corrupt"),
        ("ii_srcobj_encoded", "text_string", "a" * 1791),
    ],
)
def test_rejects_unresolved_or_invalid_source(
    table: str, column: str, value: str | int
) -> None:
    source = archive()
    source.tables[table][0][column] = value
    with pytest.raises(UnsupportedSource):
        source.dumps()


def test_rejects_duplicate_entities_and_chunks() -> None:
    for table in ["ii_entities", "ii_srcobj_encoded"]:
        source = archive()
        source.tables[table].append(deepcopy(source.tables[table][0]))
        with pytest.raises(UnsupportedSource):
            source.dumps()


def test_rejects_omitted_or_unknown_tables_and_columns() -> None:
    tables = dict(archive().tables)
    tables.pop("ii_dependencies")
    with pytest.raises(UnsupportedSource):
        Archive(tables).validate()
    source = archive()
    source.tables["ii_entities"][0]["unknown"] = 0
    with pytest.raises(UnsupportedSource):
        source.validate()


@pytest.mark.parametrize(
    "raw",
    [
        '{"format":1,"format":1,"tables":{}}',
        '{"format":true,"tables":{}}',
        '{"format":2,"tables":{}}',
        '{"format":1,"tables":{"ii_entities":[null]}}',
        "[]",
        "{}",
        "null",
    ],
)
def test_rejects_malformed_json_format(raw: str) -> None:
    with pytest.raises(UnsupportedSource):
        loads(raw)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "line one\nline two\r\n",
        "\n\\g\nrollback;\n",
        "'quoted';--",
        "\x7f\x7f2",
        "$\n=\n",
    ],
)
def test_monitor_transport_preserves_text_and_cannot_inject_commands(
    value: str,
) -> None:
    literal = sql_literal(value)
    assert "\n" not in literal and "\r" not in literal
    if value:
        assert literal.startswith("varchar(X'") and literal.endswith("')")
        assert bytes.fromhex(literal[10:-2]).decode("ascii") == value
    else:
        assert literal == "''"


@pytest.mark.parametrize("value", [True, 2**31, -(2**31) - 1, "é", "\x00"])
def test_monitor_transport_rejects_unproven_scalar_encoding(value: str | int) -> None:
    with pytest.raises(UnsupportedSource):
        sql_literal(value)


def test_monitor_transport_null_and_integer_values() -> None:
    assert sql_literal(None) == "null"
    assert sql_literal(-2147483648) == "-2147483648"


@pytest.mark.parametrize(
    "table", ["ii_components", "ii_applications", "ii_srcobj_encoded"]
)
def test_rejects_missing_current_source_rows(table: str) -> None:
    source = archive()
    source.tables[table].clear()
    with pytest.raises(UnsupportedSource):
        source.validate()


def test_rejects_duplicate_current_metadata_and_include_sequence() -> None:
    for table in ["ii_components", "ii_applications", "ii_incl_apps"]:
        source = archive()
        source.tables[table].append(dict(source.tables[table][0]))
        with pytest.raises(UnsupportedSource):
            source.validate()


def test_rejects_source_kind_mismatch() -> None:
    source = archive()
    source.tables["ii_srcobj_encoded"][0]["entity_id"] = 2
    source.tables["ii_srcobj_encoded"][1]["entity_id"] = 4
    with pytest.raises(UnsupportedSource, match="kind_mismatch"):
        source.validate()

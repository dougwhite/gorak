from gorak.database import ComponentSyncMetadata
from gorak.domain import Application, ComponentInfo
from gorak.sql_output import (
    parse_app_list_output,
    parse_component_list_output,
    parse_component_sync_metadata_output,
    parse_include_list_output,
    table_rows,
)

APP_LIST_OUTPUT = """
INGRES TERMINAL MONITOR Copyright 2024 Actian Corporation
continue
* * * * /* SQL Startup File */
select e.entity_name as application_name, a.proc_start as start_component, e.short_remark
from ii_applications a
left join ii_entities e on a.entity_id = e.entity_id
Executing . . .


+--------------------------------+--------------------------------+------------------------------------------------------------+
|application_name                |start_component                 |short_remark                                                |
+--------------------------------+--------------------------------+------------------------------------------------------------+
|sample_app                      |                                |Example application                                         |
|orders_app                      |fm_order_entry                  |Order entry screens                                         |
|shared_library                  |                                |Shared utility components                                   |
|empty_shell                     |                                |                                                            |
+--------------------------------+--------------------------------+------------------------------------------------------------+
(4 rows)

Your SQL statement(s) have been committed.
"""

COMPONENT_LIST_OUTPUT = """
INGRES TERMINAL MONITOR Copyright 2024 Actian Corporation
continue
* * * * * * * * /* SQL Startup File */
select ea.entity_name as application_name, e.entity_name as component_name, e.entity_type, e.short_remark
from ii_entities e
left join ii_entities ea on e.folder_id = ea.entity_id
left join ii_applications a on ea.base_entity_id = a.entity_id
where e.base_entity_id = 0
and e.folder_id != 0
and ea.entity_name = 'sample_app'
Executing . . .


+--------------------------------+--------------------------------+--------------------------------+------------------------------------------------------------+
|application_name                |component_name                  |entity_type                     |short_remark                                                |
+--------------------------------+--------------------------------+--------------------------------+------------------------------------------------------------+
|sample_app                      |uc_order                        |classsource                     |Order model                                                 |
|sample_app                      |p4_check_order                  |proc4glsource                   |                                                            |
|sample_app                      |fm_order_entry                  |framesource                     |Main order entry screen                                     |
+--------------------------------+--------------------------------+--------------------------------+------------------------------------------------------------+
(3 rows)

Your SQL statement(s) have been committed.
"""

INCLUDE_LIST_OUTPUT = """
+--------------------------------+--------------------------------+----------------------------------------------------------------+-------------+
|application_name                |incl_name                       |incl_filename                                                   |incl_sequence|
+--------------------------------+--------------------------------+----------------------------------------------------------------+-------------+
|sample_app                      |source_include                  |                                                                |            1|
|sample_app                      |image_include                   |image_include.pkg                                               |            2|
|sample_app                      |core                            |core.plb                                                        |            3|
+--------------------------------+--------------------------------+----------------------------------------------------------------+-------------+
"""

COMPONENT_SYNC_METADATA_OUTPUT = """
+--------------------------------+--------------------------------+--------------------------------+--------------+-----------------+--------------+-------------------------+-----------+--------------------------------+------------+
|application_name                |component_name                  |entity_type                     |base_entity_id|version_entity_id|version_number|alter_date               |alter_count|last_altered_by                 |current_make|
+--------------------------------+--------------------------------+--------------------------------+--------------+-----------------+--------------+-------------------------+-----------+--------------------------------+------------+
|sample_app                      |fm_start                        |framesource                     |           100|              101|            -1|2026_05_09 02:29:36 GMT  |          3|ingres                          |           2|
+--------------------------------+--------------------------------+--------------------------------+--------------+-----------------+--------------+-------------------------+-----------+--------------------------------+------------+
"""


def test_table_rows_reads_only_data_rows() -> None:
    assert table_rows(APP_LIST_OUTPUT, expected_cells=3, header="application_name") == [
        ["sample_app", "", "Example application"],
        ["orders_app", "fm_order_entry", "Order entry screens"],
        ["shared_library", "", "Shared utility components"],
        ["empty_shell", "", ""],
    ]


def test_parse_app_list_output() -> None:
    assert parse_app_list_output(APP_LIST_OUTPUT) == [
        Application(
            name="sample_app",
            start_component="",
            description="Example application",
        ),
        Application(
            name="orders_app",
            start_component="fm_order_entry",
            description="Order entry screens",
        ),
        Application(
            name="shared_library",
            start_component="",
            description="Shared utility components",
        ),
        Application(name="empty_shell", start_component="", description=""),
    ]


def test_parse_component_list_output() -> None:
    assert parse_component_list_output(COMPONENT_LIST_OUTPUT) == [
        ComponentInfo(
            application_name="sample_app",
            name="uc_order",
            type="classsource",
            description="Order model",
        ),
        ComponentInfo(
            application_name="sample_app",
            name="p4_check_order",
            type="proc4glsource",
            description="",
        ),
        ComponentInfo(
            application_name="sample_app",
            name="fm_order_entry",
            type="framesource",
            description="Main order entry screen",
        ),
    ]


def test_parse_include_list_output() -> None:
    assert parse_include_list_output(INCLUDE_LIST_OUTPUT) == [
        "source_include",
        {"name": "image_include", "image": "image_include.pkg"},
    ]


def test_parse_component_sync_metadata_output() -> None:
    assert parse_component_sync_metadata_output(COMPONENT_SYNC_METADATA_OUTPUT) == [
        ComponentSyncMetadata(
            application_name="sample_app",
            component_name="fm_start",
            entity_type="framesource",
            base_entity_id=100,
            version_entity_id=101,
            version_number=-1,
            alter_date="2026_05_09 02:29:36 GMT",
            alter_count=3,
            last_altered_by="ingres",
            current_make=2,
        )
    ]

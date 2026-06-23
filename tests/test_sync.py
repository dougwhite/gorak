from pathlib import Path

from pytest import MonkeyPatch

from gorak import export as export_module
from gorak import sync as sync_module
from gorak.connection import OpenRoadConnection
from gorak.database import ComponentSyncMetadata, OdbcSettings
from gorak.project import GorakContext, GorakProject
from gorak.sync import sync_project
from gorak.sync_state import component_key, load_state, save_state

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "fm_example_frame.xml"


def child_names(path: Path) -> set[str]:
    return {child.name for child in path.iterdir()}


def settings() -> OdbcSettings:
    return OdbcSettings(
        driver="Ingres AC",
        host="db-host.example",
        listen_address="II7",
        database="source_db",
        user="ingres",
        password="secret",
    )


def connection() -> OpenRoadConnection:
    return OpenRoadConnection(
        "local",
        "myvnode",
        "exampledb",
        None,
        sql_backend="odbc",
        odbc_settings=settings(),
    )


def metadata(
    component_name: str = "fm_start",
    alter_count: int = 3,
) -> ComponentSyncMetadata:
    return ComponentSyncMetadata(
        application_name="sample_app",
        component_name=component_name,
        entity_type="framesource",
        base_entity_id=100,
        version_entity_id=101,
        version_number=-1,
        alter_date="2026_05_09 02:29:36 GMT",
        alter_count=alter_count,
        last_altered_by="ingres",
        current_make=2,
    )


def write_project(root: Path) -> GorakContext:
    (root / "sample_app").mkdir()
    (root / "sample_app" / "app.json").write_text("{}\n")
    return GorakContext(project=GorakProject(root=root, name="repo"), env={})


def test_sync_exports_components_missing_from_state(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    context = write_project(tmp_path)
    calls: list[object] = []
    metadata_calls = []

    def fake_read_all_component_sync_metadata(
        connection: OpenRoadConnection,
    ) -> list[ComponentSyncMetadata]:
        metadata_calls.append(connection)
        return [metadata()]

    monkeypatch.setattr(
        sync_module,
        "read_all_component_sync_metadata",
        fake_read_all_component_sync_metadata,
    )

    def fake_backup_component(
        vnode: str,
        database: str,
        app: str,
        component: str,
        output_path: Path,
    ) -> str:
        calls.append((vnode, database, app, component, output_path))
        output_path.write_text(FIXTURE_PATH.read_text())
        return str(output_path)

    monkeypatch.setattr(export_module, "local_backup_component", fake_backup_component)

    result = sync_project(connection(), context)

    assert result.checked == 1
    assert result.exported == 1
    assert metadata_calls == [connection()]
    assert calls == [
        (
            "myvnode",
            "exampledb",
            "sample_app",
            "fm_start",
            tmp_path / ".openroad" / "sample_app" / "fm_start.xml",
        )
    ]
    assert (tmp_path / "sample_app" / "fm_example_frame.w4gl").is_file()
    state = load_state(tmp_path)
    assert (
        state["components"][component_key("sample_app", "fm_start")]["alter_count"] == 3
    )


def test_sync_renames_existing_app_folder_and_state_to_database_casing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    context = write_project(tmp_path)
    item = metadata()
    item = ComponentSyncMetadata(
        application_name="Sample_App",
        component_name=item.component_name,
        entity_type=item.entity_type,
        base_entity_id=item.base_entity_id,
        version_entity_id=item.version_entity_id,
        version_number=item.version_number,
        alter_date=item.alter_date,
        alter_count=item.alter_count,
        last_altered_by=item.last_altered_by,
        current_make=item.current_make,
    )
    save_state(
        tmp_path,
        {
            "version": 1,
            "components": {
                component_key("sample_app", "fm_start"): {
                    "version_entity_id": 999,
                    "alter_date": "old",
                    "alter_count": 1,
                }
            },
        },
    )
    monkeypatch.setattr(
        sync_module,
        "read_all_component_sync_metadata",
        lambda connection: [item],
    )

    def fake_backup_component(
        vnode: str,
        database: str,
        app: str,
        component: str,
        output_path: Path,
    ) -> str:
        output_path.write_text(FIXTURE_PATH.read_text())
        return str(output_path)

    monkeypatch.setattr(export_module, "local_backup_component", fake_backup_component)

    sync_project(connection(), context)

    assert "sample_app" not in child_names(tmp_path)
    assert (tmp_path / "Sample_App" / "app.json").is_file()
    state = load_state(tmp_path)
    assert component_key("sample_app", "fm_start") not in state["components"]
    assert component_key("Sample_App", "fm_start") in state["components"]


def test_sync_skips_unchanged_components(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    context = write_project(tmp_path)
    item = metadata()
    save_state(
        tmp_path,
        {
            "version": 1,
            "components": {
                component_key("sample_app", "fm_start"): {
                    "version_entity_id": item.version_entity_id,
                    "alter_date": item.alter_date,
                    "alter_count": item.alter_count,
                }
            },
        },
    )
    monkeypatch.setattr(
        sync_module,
        "read_all_component_sync_metadata",
        lambda connection: [item],
    )
    monkeypatch.setattr(
        sync_module,
        "export_component_to_paths",
        lambda *args, **kwargs: raise_export_called(),
    )

    result = sync_project(connection(), context)

    assert result.checked == 1
    assert result.exported == 0


def test_sync_exports_full_app_when_multiple_components_changed(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    context = write_project(tmp_path)
    calls = []
    items = [metadata("fm_start", 3), metadata("fm_other", 4)]

    monkeypatch.setattr(
        sync_module,
        "read_all_component_sync_metadata",
        lambda connection: items,
    )

    def fake_export_application_to_paths(
        connection: OpenRoadConnection,
        app: str,
        paths: export_module.ApplicationExportPaths,
        progress: object,
    ) -> object:
        calls.append((app, paths))
        return object()

    monkeypatch.setattr(
        sync_module,
        "export_application_to_paths",
        fake_export_application_to_paths,
    )

    result = sync_project(connection(), context)

    assert result.checked == 2
    assert result.exported == 2
    assert calls == [
        (
            "sample_app",
            export_module.application_export_paths(tmp_path, "sample_app"),
        )
    ]


def raise_export_called() -> None:
    raise AssertionError("unchanged component should not export")

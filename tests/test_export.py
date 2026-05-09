from pathlib import Path

import pytest
from pytest import MonkeyPatch

from gorak import export as export_module
from gorak.connection import OpenRoadConnection
from gorak.database import OdbcSettings
from gorak.domain import Application, Component, ComponentInfo
from gorak.export import (
    application_export_paths,
    application_metadata,
    apply_field_default_inheritance,
    component_export_paths,
    encode_xml_file,
    export_application,
    export_application_to_paths,
    export_component,
    export_component_to_paths,
    project_component_export_paths,
    read_application,
    read_applications,
    read_components,
    read_includes,
    write_app_metadata,
)
from gorak.project import GorakContext, GorakProject, ProjectError, write_json
from gorak.remote import RemoteHost

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "fm_example_frame.xml"
FULL_APP_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "gorak_examples.xml"


def test_component_export_paths_use_openroad_cache_and_w4gl_source() -> None:
    assert component_export_paths(Path("repo"), "sample_app", "p4_start") == (
        export_module.ComponentExportPaths(
            xml_path=Path("repo/.openroad/sample_app/p4_start.xml"),
            w4gl_path=Path("repo/sample_app/p4_start.w4gl"),
        )
    )


def test_application_export_paths_use_single_openroad_cache_file() -> None:
    assert application_export_paths(Path("repo"), "sample_app").xml_path == Path(
        "repo/.openroad/sample_app/sample_app.xml"
    )


def test_encode_xml_file_returns_w4gl_text() -> None:
    output = encode_xml_file(str(FIXTURE_PATH))

    assert "[framesource]" in output
    assert "===" in output
    assert "initialize()=" in output


def test_application_metadata_uses_openroad_application_values() -> None:
    assert application_metadata(
        Application(
            name="sample_app",
            start_component="fm_start",
            description="Example application",
        )
    ) == {
        "starting_component": "fm_start",
        "description": "Example application",
        "included_applications": [],
    }


def test_application_metadata_preserves_existing_included_applications() -> None:
    assert application_metadata(
        Application(
            name="sample_app",
            start_component="fm_start",
            description="Example application",
        ),
        existing={"included_applications": ["core", "ui"]},
    )["included_applications"] == ["core", "ui"]


def test_application_metadata_uses_exported_included_applications() -> None:
    assert application_metadata(
        Application(
            name="sample_app",
            start_component="fm_start",
            description="Example application",
        ),
        existing={"included_applications": ["old_include"]},
        included_applications=[
            "source_include",
            {"name": "image_include", "image": "image_include.pkg"},
        ],
    )["included_applications"] == [
        "source_include",
        {"name": "image_include", "image": "image_include.pkg"},
    ]


def test_write_app_metadata_writes_app_json(tmp_path: Path) -> None:
    path = write_app_metadata(
        root=tmp_path,
        application=Application(
            name="sample_app",
            start_component="fm_start",
            description="Example application",
        ),
    )

    assert path == tmp_path / "sample_app" / "app.json"
    assert path.read_text() == (
        "{\n"
        '    "starting_component": "fm_start",\n'
        '    "description": "Example application",\n'
        '    "included_applications": []\n'
        "}\n"
    )


def test_export_component_requires_output_outside_project() -> None:
    with pytest.raises(ProjectError, match="--output is required outside"):
        export_component(
            connection=OpenRoadConnection("local", "myvnode", "exampledb", None),
            context=GorakContext(project=None, env={}),
            app="sample_app",
            component="p4_start",
            output_path=None,
        )


def test_export_application_requires_output_outside_project() -> None:
    with pytest.raises(ProjectError, match="--output is required outside"):
        export_application(
            connection=OpenRoadConnection("local", "myvnode", "exampledb", None),
            context=GorakContext(project=None, env={}),
            app="sample_app",
            output_path=None,
            progress=None,
        )


def test_export_component_rejects_output_inside_project(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="--output is only supported outside"):
        export_component(
            connection=OpenRoadConnection("local", "myvnode", "exampledb", None),
            context=GorakContext(
                project=GorakProject(root=tmp_path, name="repo"),
                env={},
            ),
            app="sample_app",
            component="p4_start",
            output_path="p4_start.w4gl",
        )


def test_export_application_rejects_output_inside_project(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="--output is only supported outside"):
        export_application(
            connection=OpenRoadConnection("local", "myvnode", "exampledb", None),
            context=GorakContext(
                project=GorakProject(root=tmp_path, name="repo"),
                env={},
            ),
            app="sample_app",
            output_path=str(tmp_path / "backup"),
            progress=None,
        )


def test_project_component_export_paths_requires_project() -> None:
    with pytest.raises(ProjectError, match="requires a gorak project"):
        project_component_export_paths(
            GorakContext(project=None, env={}),
            "sample_app",
            "p4_start",
        )


def test_export_component_to_paths_uses_local_backend(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[object] = []
    paths = component_export_paths(tmp_path, "sample_app", "p4_start")

    def fake_local_backup_component(
        vnode: str,
        database: str,
        app: str,
        component: str,
        output_path: Path,
    ) -> str:
        calls.append((vnode, database, app, component, output_path))
        output_path.write_text(FIXTURE_PATH.read_text())
        return str(output_path)

    monkeypatch.setattr(
        export_module,
        "local_backup_component",
        fake_local_backup_component,
    )

    result = export_component_to_paths(
        connection=OpenRoadConnection("local", "myvnode", "exampledb", None),
        app="sample_app",
        component="p4_start",
        paths=paths,
    )

    assert result == tmp_path / "sample_app" / "fm_example_frame.w4gl"
    assert calls == [("myvnode", "exampledb", "sample_app", "p4_start", paths.xml_path)]
    assert paths.xml_path.read_text() == FIXTURE_PATH.read_text()
    assert "[framesource]" in result.read_text()


def test_export_component_to_paths_uses_xml_component_name_for_w4gl_filename(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    # Real OpenROAD exports may preserve mixed-case names even when the CLI
    # request used a lower-case component name.
    paths = component_export_paths(tmp_path, "sample_app", "g_log")
    xml = (
        '<?xml version="1.0"?>'
        '<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<COMPONENT name="G_LOG" xsi:type="proc4glsource">'
        "<script><![CDATA[main() = {}]]></script>"
        "</COMPONENT>"
        "</OPENROAD>"
    )

    def fake_local_backup_component(
        vnode: str,
        database: str,
        app: str,
        component: str,
        output_path: Path,
    ) -> str:
        output_path.write_text(xml)
        return str(output_path)

    monkeypatch.setattr(
        export_module,
        "local_backup_component",
        fake_local_backup_component,
    )

    result = export_component_to_paths(
        connection=OpenRoadConnection("local", "myvnode", "exampledb", None),
        app="sample_app",
        component="g_log",
        paths=paths,
    )

    assert result == tmp_path / "sample_app" / "G_LOG.w4gl"
    assert result.is_file()
    assert not paths.w4gl_path.exists()


def test_export_application_to_paths_uses_local_backend(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[object] = []
    paths = application_export_paths(tmp_path, "sample_app")

    def fake_local_backup_application(
        vnode: str,
        database: str,
        app: str,
        output_path: Path,
    ) -> str:
        calls.append((vnode, database, app, output_path))
        output_path.write_text(FULL_APP_FIXTURE_PATH.read_text())
        return str(output_path)

    monkeypatch.setattr(
        export_module,
        "local_backup_application",
        fake_local_backup_application,
    )

    exported = export_application_to_paths(
        connection=OpenRoadConnection("local", "myvnode", "exampledb", None),
        app="sample_app",
        paths=paths,
        progress=None,
    )

    assert calls == [("myvnode", "exampledb", "sample_app", paths.xml_path)]
    assert paths.xml_path.read_text() == FULL_APP_FIXTURE_PATH.read_text()
    assert [component.name for component in exported.components] == [
        "fm_example_frame",
        "p4_example_procedure",
        "uc_example_userclass",
    ]
    assert (tmp_path / "field_defaults.json").is_file()
    assert (tmp_path / "sample_app" / "field_defaults.json").read_text() == "{}\n"
    assert (tmp_path / "sample_app" / "fm_example_frame.w4gl").is_file()
    assert (tmp_path / "sample_app" / "fm_example_frame.wml").is_file()
    assert not (tmp_path / "sample_app" / "p4_example_procedure.wml").exists()
    assert "[fielddefaults]" not in (
        tmp_path / "sample_app" / "fm_example_frame.w4gl"
    ).read_text()
    assert (tmp_path / "sample_app" / "p4_example_procedure.w4gl").is_file()
    assert (tmp_path / "sample_app" / "uc_example_userclass.w4gl").is_file()


def test_apply_field_default_inheritance_keeps_changed_nested_frame_overrides(
    tmp_path: Path,
) -> None:
    app_dir = tmp_path / "sample_app"
    app_dir.mkdir()
    write_json(
        tmp_path / "field_defaults.json",
        {
            "field_styles": [
                {
                    "type": "controlbutton",
                    "group": "controlbutton",
                    "properties": {"optionmenu": {"bgcolor": "2", "fgcolor": "1"}},
                }
            ]
        },
    )
    write_json(app_dir / "field_defaults.json", {})
    component = Component(
        name="fm_start",
        type="framesource",
        props={
            "fielddefaults": {
                "field_styles": [
                    {
                        "type": "controlbutton",
                        "group": "controlbutton",
                        "properties": {
                            "optionmenu": {"bgcolor": "70", "fgcolor": "1"}
                        },
                    }
                ]
            }
        },
    )

    apply_field_default_inheritance(tmp_path, "sample_app", [component])

    assert component.props["fielddefaults"] == {
        "field_styles": [
            {
                "type": "controlbutton",
                "group": "controlbutton",
                "properties": {"optionmenu": {"bgcolor": "70", "fgcolor": "1"}},
            }
        ]
    }


def test_export_component_to_paths_uses_remote_backend(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[object] = []
    remote = RemoteHost("test", "windows-pc", r"C:\Development\gorak")
    paths = component_export_paths(tmp_path, "sample_app", "p4_start")

    def fake_backup_component(
        remote: RemoteHost,
        vnode: str,
        database: str,
        app: str,
        component: str,
    ) -> str:
        calls.append(("backup", remote, vnode, database, app, component))
        return r"C:\Development\gorak\p4_start.xml"

    def fake_download_file(
        remote: RemoteHost,
        remote_path: str,
        local_path: str,
    ) -> str:
        calls.append(("download", remote, remote_path, local_path))
        Path(local_path).write_text(FIXTURE_PATH.read_text())
        return local_path

    monkeypatch.setattr(export_module, "backup_component", fake_backup_component)
    monkeypatch.setattr(export_module, "download_file", fake_download_file)

    result = export_component_to_paths(
        connection=OpenRoadConnection("remote", "myvnode", "exampledb", remote),
        app="sample_app",
        component="p4_start",
        paths=paths,
    )

    assert calls == [
        ("backup", remote, "myvnode", "exampledb", "sample_app", "p4_start"),
        (
            "download",
            remote,
            r"C:\Development\gorak\p4_start.xml",
            str(paths.xml_path),
        ),
    ]
    assert result == tmp_path / "sample_app" / "fm_example_frame.w4gl"
    assert "[framesource]" in result.read_text()
    assert (tmp_path / "sample_app" / "fm_example_frame.wml").is_file()


def test_export_application_to_paths_uses_remote_backend(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[object] = []
    remote = RemoteHost("test", "windows-pc", r"C:\Development\gorak")
    paths = application_export_paths(tmp_path, "sample_app")

    def fake_backup_application(
        remote: RemoteHost,
        vnode: str,
        database: str,
        app: str,
    ) -> str:
        calls.append(("backup", remote, vnode, database, app))
        return r"C:\Development\gorak\sample_app.xml"

    def fake_download_file(
        remote: RemoteHost,
        remote_path: str,
        local_path: str,
    ) -> str:
        calls.append(("download", remote, remote_path, local_path))
        Path(local_path).write_text(FULL_APP_FIXTURE_PATH.read_text())
        return local_path

    monkeypatch.setattr(export_module, "backup_application", fake_backup_application)
    monkeypatch.setattr(export_module, "download_file", fake_download_file)

    export_application_to_paths(
        connection=OpenRoadConnection("remote", "myvnode", "exampledb", remote),
        app="sample_app",
        paths=paths,
        progress=None,
    )

    assert calls == [
        ("backup", remote, "myvnode", "exampledb", "sample_app"),
        (
            "download",
            remote,
            r"C:\Development\gorak\sample_app.xml",
            str(paths.xml_path),
        ),
    ]
    assert (tmp_path / "sample_app" / "fm_example_frame.w4gl").is_file()


def test_export_component_uses_project_paths(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    project = GorakProject(root=tmp_path, name="repo")
    calls: list[object] = []

    def fake_export_component_to_paths(
        connection: OpenRoadConnection,
        app: str,
        component: str,
        paths: export_module.ComponentExportPaths,
    ) -> Path:
        calls.append((connection, app, component, paths))
        return paths.w4gl_path

    monkeypatch.setattr(
        export_module,
        "export_component_to_paths",
        fake_export_component_to_paths,
    )

    path = export_component(
        connection=OpenRoadConnection("local", "myvnode", "exampledb", None),
        context=GorakContext(project=project, env={}),
        app="sample_app",
        component="p4_start",
        output_path=None,
    )

    assert path == tmp_path / "sample_app" / "p4_start.w4gl"
    assert calls == [
        (
            OpenRoadConnection("local", "myvnode", "exampledb", None),
            "sample_app",
            "p4_start",
            component_export_paths(tmp_path, "sample_app", "p4_start"),
        )
    ]


def test_read_applications_routes_to_local_backend(monkeypatch: MonkeyPatch) -> None:
    calls: list[object] = []

    def fake_local_get_app_list(vnode: str, database: str) -> list[Application]:
        calls.append((vnode, database))
        return []

    monkeypatch.setattr(export_module, "local_get_app_list", fake_local_get_app_list)

    assert (
        read_applications(OpenRoadConnection("local", "myvnode", "exampledb", None))
        == []
    )
    assert calls == [("myvnode", "exampledb")]


def test_read_applications_routes_to_odbc_sql_backend(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[object] = []
    settings = OdbcSettings(
        driver="Ingres AC",
        host="db-host.example",
        listen_address="II7",
        database="source_db",
        user="ingres",
        password="secret",
    )

    def fake_odbc_get_app_list(
        odbc_settings: OdbcSettings,
    ) -> list[Application]:
        calls.append(odbc_settings)
        return [Application("sample_app", "fm_start", "Example application")]

    monkeypatch.setattr(export_module, "odbc_get_app_list", fake_odbc_get_app_list)

    assert read_applications(
        OpenRoadConnection(
            "local",
            "myvnode",
            "exampledb",
            None,
            sql_backend="odbc",
            odbc_settings=settings,
        )
    ) == [Application("sample_app", "fm_start", "Example application")]
    assert calls == [settings]


def test_read_application_returns_matching_application(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        export_module,
        "local_get_app_list",
        lambda vnode, database: [
            Application("sample_app", "fm_start", "Example application")
        ],
    )

    assert read_application(
        OpenRoadConnection("local", "myvnode", "exampledb", None),
        "sample_app",
    ) == Application("sample_app", "fm_start", "Example application")


def test_read_application_returns_case_insensitive_match(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        export_module,
        "local_get_app_list",
        lambda vnode, database: [
            Application("orders_mixedCase", "fm_start", "Example application")
        ],
    )

    assert read_application(
        OpenRoadConnection("local", "myvnode", "exampledb", None),
        "orders_mixedcase",
    ) == Application("orders_mixedCase", "fm_start", "Example application")


def test_read_application_errors_when_application_is_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        export_module,
        "local_get_app_list",
        lambda vnode, database: [],
    )

    with pytest.raises(ProjectError, match="Application not found: missing_app"):
        read_application(
            OpenRoadConnection("local", "myvnode", "exampledb", None),
            "missing_app",
        )


def test_read_components_routes_to_remote_backend(monkeypatch: MonkeyPatch) -> None:
    calls: list[object] = []
    remote = RemoteHost("test", "windows-pc", r"C:\Development\gorak")

    def fake_get_component_list(
        remote: RemoteHost,
        vnode: str,
        database: str,
        app: str,
    ) -> list[ComponentInfo]:
        calls.append((remote, vnode, database, app))
        return []

    monkeypatch.setattr(export_module, "get_component_list", fake_get_component_list)

    assert (
        read_components(
            OpenRoadConnection("remote", "myvnode", "exampledb", remote),
            "sample_app",
        )
        == []
    )
    assert calls == [(remote, "myvnode", "exampledb", "sample_app")]


def test_read_components_routes_to_odbc_sql_backend(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[object] = []
    settings = OdbcSettings(
        driver="Ingres AC",
        host="db-host.example",
        listen_address="II7",
        database="source_db",
        user="ingres",
        password="secret",
    )

    def fake_odbc_get_component_list(
        odbc_settings: OdbcSettings,
        app: str,
    ) -> list[ComponentInfo]:
        calls.append((odbc_settings, app))
        return [ComponentInfo("sample_app", "fm_start", "framesource", "Start frame")]

    monkeypatch.setattr(
        export_module,
        "odbc_get_component_list",
        fake_odbc_get_component_list,
    )

    assert read_components(
        OpenRoadConnection(
            "remote",
            "myvnode",
            "exampledb",
            RemoteHost("test", "windows-pc", r"C:\Development\gorak"),
            sql_backend="odbc",
            odbc_settings=settings,
        ),
        "sample_app",
    ) == [ComponentInfo("sample_app", "fm_start", "framesource", "Start frame")]
    assert calls == [(settings, "sample_app")]


def test_read_includes_routes_to_local_backend(monkeypatch: MonkeyPatch) -> None:
    calls: list[object] = []

    def fake_local_get_include_list(
        vnode: str,
        database: str,
        app: str,
    ) -> list[object]:
        calls.append((vnode, database, app))
        return ["source_include"]

    monkeypatch.setattr(
        export_module,
        "local_get_include_list",
        fake_local_get_include_list,
    )

    assert read_includes(
        OpenRoadConnection("local", "myvnode", "exampledb", None),
        "sample_app",
    ) == ["source_include"]
    assert calls == [("myvnode", "exampledb", "sample_app")]

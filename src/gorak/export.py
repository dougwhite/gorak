"""Coordinate OpenROAD XML export and .w4gl source file writing."""

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from . import database as database_module
from . import local
from .connection import (
    OpenRoadConnection,
    connection_sql_backend,
    require_odbc_settings,
    require_remote_host,
)
from .domain import (
    Application,
    ApplicationExport,
    Component,
    ComponentInfo,
    IncludedApplication,
)
from .field_defaults import diff_defaults, effective_defaults
from .parser import encode_w4gl, encode_wml, parse_application_xml, parse_xml
from .project import GorakContext, ProjectError, read_json, write_json
from .remote import (
    backup_application,
    backup_component,
    download_file,
    get_app_list,
    get_component_list,
    get_include_list,
)

local_backup_application = local.backup_application
local_backup_component = local.backup_component
local_get_app_list = local.get_app_list
local_get_component_list = local.get_component_list
local_get_include_list = local.get_include_list
odbc_get_app_list = database_module.get_app_list
odbc_get_component_list = database_module.get_component_list
odbc_get_include_list = database_module.get_include_list


@dataclass(frozen=True)
class ComponentExportPaths:
    xml_path: Path
    w4gl_path: Path


@dataclass(frozen=True)
class ApplicationExportPaths:
    xml_path: Path
    source_dir: Path


def encode_xml_file(xml_path: str) -> str:
    """Parse an OpenROAD XML export and return encoded .w4gl text."""

    component = parse_xml(etree.parse(xml_path))
    return encode_w4gl(component)


def application_metadata(
    application: Application,
    existing: dict[str, object] | None = None,
    included_applications: list[IncludedApplication] | None = None,
) -> dict[str, object]:
    """Build app.json data from known metadata and preserved local-only fields."""

    existing = existing or {}
    metadata = {
        "starting_component": application.start_component,
        "description": application.description,
        "included_applications": (
            included_applications
            if included_applications is not None
            else existing.get("included_applications", [])
        ),
    }
    if application.database_name:
        metadata["database_name"] = application.database_name
    if application.database_type:
        metadata["database_type"] = application.database_type

    return metadata


def write_app_metadata(
    root: Path,
    application: Application,
    included_applications: list[IncludedApplication] | None = None,
) -> Path:
    """Write app.json while preserving local-only fields not yet exported."""

    path = root / application.name / "app.json"
    existing = read_json(path) if path.is_file() else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        path,
        application_metadata(application, existing, included_applications),
    )
    return path


def export_application(
    connection: OpenRoadConnection,
    context: GorakContext,
    app: str,
    output_path: str | None,
    progress: Callable[[str], None] | None,
) -> ApplicationExport:
    """Export one OpenROAD application into a Gorak project or output directory."""

    root = export_root(context, output_path)
    progress_message(progress, "Retrieving application metadata")
    application = read_application(connection, app)
    paths = application_export_paths(root, application.name)
    exported = export_application_to_paths(
        connection=connection,
        app=application.name,
        paths=paths,
        progress=progress,
    )
    write_app_metadata(
        root,
        merge_application_metadata(application, exported.application),
        exported.included_applications,
    )
    return exported


def merge_application_metadata(
    database_application: Application,
    exported_application: Application,
) -> Application:
    """Combine SQL metadata with values only present in full XML exports."""

    return Application(
        name=database_application.name,
        start_component=(
            database_application.start_component or exported_application.start_component
        ),
        description=database_application.description or exported_application.description,
        database_name=exported_application.database_name,
        database_type=exported_application.database_type,
    )


def export_component(
    connection: OpenRoadConnection,
    context: GorakContext,
    app: str,
    component: str,
    output_path: str | None,
) -> Path:
    """Export one component and return the .w4gl path named by the XML component."""

    validate_output_mode(context, output_path)

    if context.project is None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ComponentExportPaths(
                xml_path=Path(temp_dir) / f"{component}.xml",
                w4gl_path=Path(str(output_path)),
            )
            return export_component_to_paths(connection, app, component, paths)

    paths = project_component_export_paths(context, app, component)
    return export_component_to_paths(connection, app, component, paths)


def export_application_to_paths(
    connection: OpenRoadConnection,
    app: str,
    paths: ApplicationExportPaths,
    progress: Callable[[str], None] | None,
) -> ApplicationExport:
    """Export one full application XML and encode all top-level components."""

    paths.xml_path.parent.mkdir(parents=True, exist_ok=True)
    paths.source_dir.mkdir(parents=True, exist_ok=True)
    progress_message(progress, "Exporting full application XML")
    backup_application_xml(connection, app, paths.xml_path)

    exported = parse_application_xml(etree.parse(str(paths.xml_path)))
    apply_field_default_inheritance(paths.source_dir.parent, app, exported.components)
    for component in exported.components:
        progress_message(progress, f"Encoding component {app}::{component.name}")
        write_component_w4gl(paths.source_dir, component.name, encode_w4gl(component))
        write_component_wml(paths.source_dir, component.name, encode_wml(component))

    return exported


def export_component_to_paths(
    connection: OpenRoadConnection,
    app: str,
    component: str,
    paths: ComponentExportPaths,
) -> Path:
    """Export one component XML and encode the component named inside that XML."""

    paths.xml_path.parent.mkdir(parents=True, exist_ok=True)
    paths.w4gl_path.parent.mkdir(parents=True, exist_ok=True)
    backup_component_xml(connection, app, component, paths.xml_path)

    parsed_component = parse_xml(etree.parse(str(paths.xml_path)))
    apply_field_default_inheritance(
        paths.w4gl_path.parent.parent,
        app,
        [parsed_component],
    )
    w4gl_path = write_component_w4gl(
        paths.w4gl_path.parent,
        parsed_component.name,
        encode_w4gl(parsed_component),
    )
    write_component_wml(
        paths.w4gl_path.parent,
        parsed_component.name,
        encode_wml(parsed_component),
    )
    return w4gl_path


def apply_field_default_inheritance(
    root: Path,
    app: str,
    components: list[Component],
) -> None:
    """Move frame field defaults into repo/app defaults and leave frame diffs."""

    repo_path = root / "field_defaults.json"
    app_path = root / app / "field_defaults.json"
    repo_defaults = read_json(repo_path) if repo_path.is_file() else None
    app_defaults = read_json(app_path) if app_path.is_file() else None

    for component in components:
        props = component.props
        frame_defaults = props.pop("fielddefaults", None)
        if not isinstance(frame_defaults, dict):
            continue

        if repo_defaults is None:
            repo_defaults = frame_defaults
            write_json(repo_path, repo_defaults)

        if app_defaults is None:
            app_defaults = diff_defaults(repo_defaults, frame_defaults)
            app_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(app_path, app_defaults)

        parent_defaults = effective_defaults(repo_defaults, app_defaults, {})
        frame_override = diff_defaults(parent_defaults, frame_defaults)
        if frame_override:
            props["fielddefaults"] = frame_override


def backup_application_xml(
    connection: OpenRoadConnection,
    app: str,
    xml_path: Path,
) -> None:
    """Run the correct backend-specific full application XML export."""

    if connection.backend == "local":
        local_backup_application(
            vnode=connection.vnode,
            database=connection.database,
            app=app,
            output_path=xml_path,
        )
        return

    remote = require_remote_host(connection)
    remote_xml_path = backup_application(
        remote=remote,
        vnode=connection.vnode,
        database=connection.database,
        app=app,
    )
    download_file(remote=remote, remote_path=remote_xml_path, local_path=str(xml_path))


def backup_component_xml(
    connection: OpenRoadConnection,
    app: str,
    component: str,
    xml_path: Path,
) -> None:
    """Run the correct backend-specific single component XML export."""

    if connection.backend == "local":
        local_backup_component(
            vnode=connection.vnode,
            database=connection.database,
            app=app,
            component=component,
            output_path=xml_path,
        )
        return

    remote = require_remote_host(connection)
    remote_xml_path = backup_component(
        remote=remote,
        vnode=connection.vnode,
        database=connection.database,
        app=app,
        component=component,
    )
    download_file(remote=remote, remote_path=remote_xml_path, local_path=str(xml_path))


def read_applications(connection: OpenRoadConnection) -> list[Application]:
    sql_backend = connection_sql_backend(connection)
    if sql_backend == "odbc":
        return odbc_get_app_list(require_odbc_settings(connection))
    if sql_backend == "local":
        return local_get_app_list(connection.vnode, connection.database)

    return get_app_list(
        remote=require_remote_host(connection),
        vnode=connection.vnode,
        database=connection.database,
    )


def read_application(connection: OpenRoadConnection, app: str) -> Application:
    """Find application metadata, allowing case-insensitive CLI input."""

    applications = read_applications(connection)
    for application in applications:
        if application.name == app:
            return application

    for application in applications:
        if application.name.lower() == app.lower():
            return application

    raise ProjectError(f"Application not found: {app}")


def read_components(connection: OpenRoadConnection, app: str) -> list[ComponentInfo]:
    sql_backend = connection_sql_backend(connection)
    if sql_backend == "odbc":
        return odbc_get_component_list(require_odbc_settings(connection), app)
    if sql_backend == "local":
        return local_get_component_list(
            vnode=connection.vnode,
            database=connection.database,
            app=app,
        )

    return get_component_list(
        remote=require_remote_host(connection),
        vnode=connection.vnode,
        database=connection.database,
        app=app,
    )


def read_includes(
    connection: OpenRoadConnection,
    app: str,
) -> list[IncludedApplication]:
    sql_backend = connection_sql_backend(connection)
    if sql_backend == "odbc":
        return odbc_get_include_list(require_odbc_settings(connection), app)
    if sql_backend == "local":
        return local_get_include_list(
            vnode=connection.vnode,
            database=connection.database,
            app=app,
        )

    return get_include_list(
        remote=require_remote_host(connection),
        vnode=connection.vnode,
        database=connection.database,
        app=app,
    )


def project_component_export_paths(
    context: GorakContext,
    app: str,
    component: str,
) -> ComponentExportPaths:
    if context.project is None:
        raise ProjectError("Component export requires a gorak project")

    return component_export_paths(context.project.root, app, component)


def export_root(context: GorakContext, output_path: str | None) -> Path:
    """Return the output root after enforcing project/output mode rules."""

    validate_output_mode(context, output_path)
    if context.project is not None:
        return context.project.root

    return Path(str(output_path))


def validate_output_mode(context: GorakContext, output_path: str | None) -> None:
    if context.project is None and output_path is None:
        raise ProjectError("--output is required outside a gorak project")
    if context.project is not None and output_path is not None:
        raise ProjectError("--output is only supported outside a gorak project")


def application_export_paths(root: Path, app: str) -> ApplicationExportPaths:
    return ApplicationExportPaths(
        xml_path=root / ".openroad" / app / f"{app}.xml",
        source_dir=root / app,
    )


def component_export_paths(
    root: Path, app: str, component: str
) -> ComponentExportPaths:
    return ComponentExportPaths(
        xml_path=root / ".openroad" / app / f"{component}.xml",
        w4gl_path=root / app / f"{component}.w4gl",
    )


def progress_message(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def write_component_w4gl(source_dir: Path, component_name: str, content: str) -> Path:
    """Write a component using the OpenROAD XML name as the source filename."""

    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / f"{component_name}.w4gl"
    path.write_text(content)
    return path


def write_component_wml(
    source_dir: Path,
    component_name: str,
    content: str | None,
) -> Path | None:
    """Write frame markup when a component has a visual source tree."""

    if content is None:
        return None

    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / f"{component_name}.wml"
    path.write_text(content + "\n")
    return path

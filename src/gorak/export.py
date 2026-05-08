import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from . import local
from .connection import OpenRoadConnection, require_remote_host
from .domain import Application, ApplicationExport, ComponentInfo
from .parser import encode_w4gl, parse_application_xml, parse_xml
from .project import GorakContext, ProjectError, read_json, write_json
from .remote import (
    backup_application,
    backup_component,
    download_file,
    get_app_list,
    get_component_list,
)

local_backup_application = local.backup_application
local_backup_component = local.backup_component
local_get_app_list = local.get_app_list
local_get_component_list = local.get_component_list


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
) -> dict[str, object]:
    """Build app.json data from known metadata and preserved local-only fields."""

    existing = existing or {}
    return {
        "starting_component": application.start_component,
        "description": application.description,
        "included_applications": existing.get("included_applications", []),
    }


def write_app_metadata(root: Path, application: Application) -> Path:
    path = root / application.name / "app.json"
    existing = read_json(path) if path.is_file() else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, application_metadata(application, existing))
    return path


def export_application(
    connection: OpenRoadConnection,
    context: GorakContext,
    app: str,
    output_path: str | None,
    progress: Callable[[str], None] | None,
) -> ApplicationExport:
    if context.project is None and output_path is None:
        raise ProjectError("--output is required outside a gorak project")
    if context.project is not None and output_path is not None:
        raise ProjectError("--output is only supported outside a gorak project")

    root = (
        context.project.root
        if context.project is not None
        else Path(str(output_path))
    )
    progress_message(progress, "Retrieving application metadata")
    application = read_application(connection, app)
    paths = application_export_paths(root, application.name)
    exported = export_application_to_paths(
        connection=connection,
        app=application.name,
        paths=paths,
        progress=progress,
    )
    write_app_metadata(root, application)
    return exported


def export_component(
    connection: OpenRoadConnection,
    context: GorakContext,
    app: str,
    component: str,
    output_path: str | None,
) -> Path:
    if context.project is None and output_path is None:
        raise ProjectError("--output is required outside a gorak project")
    if context.project is not None and output_path is not None:
        raise ProjectError("--output is only supported outside a gorak project")

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
    paths.xml_path.parent.mkdir(parents=True, exist_ok=True)
    paths.source_dir.mkdir(parents=True, exist_ok=True)
    progress_message(progress, "Exporting full application XML")
    if connection.backend == "local":
        local_backup_application(
            vnode=connection.vnode,
            database=connection.database,
            app=app,
            output_path=paths.xml_path,
        )
    else:
        remote = require_remote_host(connection)
        remote_xml_path = backup_application(
            remote=remote,
            vnode=connection.vnode,
            database=connection.database,
            app=app,
        )
        download_file(
            remote=remote,
            remote_path=remote_xml_path,
            local_path=str(paths.xml_path),
        )

    exported = parse_application_xml(etree.parse(str(paths.xml_path)))
    for component in exported.components:
        progress_message(progress, f"Encoding component {app}::{component.name}")
        write_component_w4gl(paths.source_dir, component.name, encode_w4gl(component))

    return exported


def export_component_to_paths(
    connection: OpenRoadConnection,
    app: str,
    component: str,
    paths: ComponentExportPaths,
) -> Path:
    paths.xml_path.parent.mkdir(parents=True, exist_ok=True)
    paths.w4gl_path.parent.mkdir(parents=True, exist_ok=True)
    if connection.backend == "local":
        local_backup_component(
            vnode=connection.vnode,
            database=connection.database,
            app=app,
            component=component,
            output_path=paths.xml_path,
        )
    else:
        remote = require_remote_host(connection)
        remote_xml_path = backup_component(
            remote=remote,
            vnode=connection.vnode,
            database=connection.database,
            app=app,
            component=component,
        )
        download_file(
            remote=remote,
            remote_path=remote_xml_path,
            local_path=str(paths.xml_path),
        )
    parsed_component = parse_xml(etree.parse(str(paths.xml_path)))
    return write_component_w4gl(
        paths.w4gl_path.parent,
        parsed_component.name,
        encode_w4gl(parsed_component),
    )


def read_applications(connection: OpenRoadConnection) -> list[Application]:
    if connection.backend == "local":
        return local_get_app_list(connection.vnode, connection.database)

    return get_app_list(
        remote=require_remote_host(connection),
        vnode=connection.vnode,
        database=connection.database,
    )


def read_application(connection: OpenRoadConnection, app: str) -> Application:
    applications = read_applications(connection)
    for application in applications:
        if application.name == app:
            return application

    for application in applications:
        if application.name.lower() == app.lower():
            return application

    raise ProjectError(f"Application not found: {app}")


def read_components(connection: OpenRoadConnection, app: str) -> list[ComponentInfo]:
    if connection.backend == "local":
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


def project_component_export_paths(
    context: GorakContext,
    app: str,
    component: str,
) -> ComponentExportPaths:
    if context.project is None:
        raise ProjectError("Component export requires a gorak project")

    return component_export_paths(context.project.root, app, component)


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
    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / f"{component_name}.w4gl"
    path.write_text(content)
    return path

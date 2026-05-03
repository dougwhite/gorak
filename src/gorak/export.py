import tempfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from . import local
from .connection import OpenRoadConnection, require_remote_host
from .domain import Application, ComponentInfo
from .parser import encode_w4gl, parse_xml
from .project import GorakContext, ProjectError
from .remote import backup_component, download_file, get_app_list, get_component_list

local_backup_component = local.backup_component
local_get_app_list = local.get_app_list
local_get_component_list = local.get_component_list


@dataclass(frozen=True)
class ComponentExportPaths:
    xml_path: Path
    w4gl_path: Path


def encode_xml_file(xml_path: str) -> str:
    """Parse an OpenROAD XML export and return encoded .w4gl text."""

    component = parse_xml(etree.parse(xml_path))
    return encode_w4gl(component)


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
            export_component_to_paths(connection, app, component, paths)
            return paths.w4gl_path

    paths = project_component_export_paths(context, app, component)
    export_component_to_paths(connection, app, component, paths)
    return paths.w4gl_path


def export_component_to_paths(
    connection: OpenRoadConnection,
    app: str,
    component: str,
    paths: ComponentExportPaths,
) -> None:
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
    paths.w4gl_path.write_text(encode_xml_file(str(paths.xml_path)))


def read_applications(connection: OpenRoadConnection) -> list[Application]:
    if connection.backend == "local":
        return local_get_app_list(connection.vnode, connection.database)

    return get_app_list(
        remote=require_remote_host(connection),
        vnode=connection.vnode,
        database=connection.database,
    )


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


def component_export_paths(
    root: Path, app: str, component: str
) -> ComponentExportPaths:
    return ComponentExportPaths(
        xml_path=root / ".openroad" / app / f"{component}.xml",
        w4gl_path=root / app / f"{component}.w4gl",
    )

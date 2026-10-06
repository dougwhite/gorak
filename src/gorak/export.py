"""Coordinate OpenROAD XML export and .w4gl source file writing."""

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2, rmtree
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .image_assets import AssetWriter

from lxml import etree

from . import database as database_module
from . import local
from .component_defaults import encode_source_w4gl, write_component_defaults
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
from .export_failures import (
    ComponentProjectionError,
    ExportFailure,
    cached_components,
    finalize_baseline,
)
from .local import LocalCommandError
from .odbc_runtime import odbc_error_types
from .parser import (
    FRAME_COMPONENT_TYPES,
    FRAME_MARKUP_CHILDREN,
    encode_frame_markup,
    parse_application_xml,
    parse_component_node,
    parse_xml,
)
from .project import GorakContext, ProjectError, read_json, write_json
from .query_metadata import write_queries
from .remote import (
    RemoteCommandError,
    backup_application,
    backup_component,
    download_file,
    get_all_component_sync_metadata,
    get_app_list,
    get_component_list,
    get_include_list,
)
from .revision_route import validate_source_route
from .sync_state import update_component_entries
from .writer_launch import local_writer_command

local_backup_application = local.backup_application
local_backup_component = local.backup_component
local_get_app_list = local.get_app_list
local_get_component_list = local.get_component_list
local_get_include_list = local.get_include_list
local_get_component_sync_metadata = local.get_component_sync_metadata
local_get_all_component_sync_metadata = local.get_all_component_sync_metadata
odbc_get_app_list = database_module.get_app_list
odbc_get_component_list = database_module.get_component_list
odbc_get_include_list = database_module.get_include_list
odbc_get_component_sync_metadata = database_module.get_component_sync_metadata
odbc_get_all_component_sync_metadata = database_module.get_all_component_sync_metadata


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

    from .portable_source import read_document

    component = parse_xml(read_document(Path(xml_path)))
    return encode_source_w4gl(component)


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

    if application.window_icon:
        metadata["window_icon"] = application.window_icon
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
    from .sync_guard import can_bind_fresh_export, save_binding

    bind_after_export = can_bind_fresh_export(connection, root)
    progress_message(progress, "Retrieving application metadata")
    application = read_application(connection, app)
    normalize_application_paths(root, application.name, progress)
    paths = application_export_paths(root, application.name)
    previous = cached_components(paths.xml_path.parent)
    exported = export_application_to_paths(
        connection=connection,
        app=application.name,
        paths=paths,
        progress=progress,
    )
    finalize_baseline(paths.xml_path, exported.failures, previous)
    merged_application = merge_application_metadata(application, exported.application)
    write_app_metadata(
        root,
        merged_application,
        exported.included_applications,
    )
    if bind_after_export:
        save_binding(connection, root)
    if not exported.failures:
        record_component_sync_metadata_best_effort(
            connection,
            root,
            application.name,
            progress,
        )
    return ApplicationExport(
        application=merged_application,
        components=exported.components,
        included_applications=exported.included_applications,
        failures=exported.failures,
    )


def merge_application_metadata(
    database_application: Application,
    exported_application: Application,
) -> Application:
    """Keep catalog identity and preserve full XML metadata without SQL escaping."""

    return Application(
        name=database_application.name,
        start_component=(
            database_application.start_component or exported_application.start_component
        ),
        description=exported_application.description,
        database_name=exported_application.database_name,
        database_type=exported_application.database_type,
        window_icon=exported_application.window_icon,
    )


def export_component(
    connection: OpenRoadConnection,
    context: GorakContext,
    app: str,
    component: str,
    output_path: str | None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Export one component and return the .w4gl path named by the XML component."""

    validate_output_mode(context, output_path)

    if context.project is None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ComponentExportPaths(
                xml_path=Path(temp_dir) / f"{component}.xml",
                w4gl_path=Path(str(output_path)),
            )
            return export_component_to_paths(
                connection, app, component, paths, progress
            )

    from .sync_guard import can_bind_fresh_export, save_binding

    bind_after_export = can_bind_fresh_export(connection, context.project.root)
    canonical_app = canonical_application_name(connection, context.project.root, app)
    normalize_application_paths(context.project.root, canonical_app, progress)
    paths = project_component_export_paths(context, canonical_app, component)
    path = export_component_to_paths(
        connection,
        canonical_app,
        component,
        paths,
        progress,
    )
    if bind_after_export:
        save_binding(connection, context.project.root)
    record_component_sync_metadata_best_effort(
        connection,
        context.project.root,
        canonical_app,
        progress,
    )
    return path


def export_application_to_paths(
    connection: OpenRoadConnection,
    app: str,
    paths: ApplicationExportPaths,
    progress: Callable[[str], None] | None,
    *,
    asset_origins: Path | None = None,
) -> ApplicationExport:
    """Export one full application XML and encode all top-level components."""

    paths.xml_path.parent.mkdir(parents=True, exist_ok=True)
    paths.source_dir.mkdir(parents=True, exist_ok=True)
    progress_message(progress, "Exporting full application XML")
    backup_application_xml(connection, app, paths.xml_path)

    from .portable_source import read_document

    tree = read_document(paths.xml_path)
    if tree.tag != "OPENROAD" or any(
        n.tag not in {"APPLICATION", "COMPONENT"} for n in tree
    ):
        raise ProjectError("Unsupported export document structure")
    from .image_assets import AssetWriter, externalize

    catalog = read_components(connection, app)
    nodes = tree.findall("COMPONENT")
    names = [node.get("name") for node in nodes]
    if any(not name for name in names) or len(
        {str(n).casefold() for n in names}
    ) != len(names):
        raise ProjectError("Missing or duplicate exported component names")
    writer = AssetWriter(paths.source_dir, origins_from=asset_origins)
    application_node = tree.find("APPLICATION")
    if application_node is None or len(tree.findall("APPLICATION")) != 1:
        raise ProjectError("Expected one exported application")
    application_tree = etree.Element("OPENROAD")
    application_tree.append(
        externalize(application_node, paths.source_dir, app, writer=writer)
    )
    exported = parse_application_xml(application_tree)
    failures: list[ExportFailure] = []

    def failed(name: str, reason: str) -> None:
        failure = ExportFailure(app, name, reason)
        failures.append(failure)
        progress_message(progress, failure.message())

    present = {str(name).casefold() for name in names}
    for item in catalog:
        if item.name.casefold() not in present:
            failed(
                item.name,
                "Component is present in the catalog but missing from the native XML export",
            )
    components: list[Component] = []
    for native in nodes:
        name = str(native.get("name"))
        progress_message(progress, f"Encoding component {app}!{name}")
        try:
            components.append(
                project_component_files(native, paths.source_dir, writer, progress)
            )
        except ComponentProjectionError as ex:
            failed(name, str(ex))
    write_json(
        paths.source_dir / "app.json",
        application_metadata(
            exported.application, included_applications=exported.included_applications
        ),
    )
    return ApplicationExport(
        exported.application, components, exported.included_applications, failures
    )


def project_component_files(
    native: etree._Element,
    source_dir: Path,
    writer: "AssetWriter",
    progress: Callable[[str], None] | None,
) -> Component:
    from .image_assets import externalize

    name = str(native.get("name"))
    # Prepare all component files before replacing any existing source. A
    # malformed query, stylesheet or bitmap must not leave a half-written frame.
    with tempfile.TemporaryDirectory(prefix="gorak-component-") as temporary:
        stage = Path(temporary) / source_dir.name
        stage.mkdir()
        for parent, target in (
            (source_dir.parent, stage.parent),
            (source_dir, stage),
        ):
            defaults = parent / "field_defaults.json"
            if defaults.exists():
                copy2(defaults, target / defaults.name)
        from .component_edits import SUPPORTED_TYPES
        from .importer import validate_name
        from .parser import NS

        try:
            validate_name(name)
            kind = native.get(f"{{{NS['xsi']}}}type")
            if kind not in SUPPORTED_TYPES:
                raise ProjectError(f"Unsupported component type: {kind}")
            node = externalize(native, source_dir, name, writer=writer)
            component = parse_component_node(node)
            apply_field_default_inheritance(
                stage.parent, stage.name, [component], source_nodes=[node]
            )
            from .class_icons import extract_icons

            extract_icons(node)
            write_queries(stage / f"{name}.w4gl", component.queries)
            write_component_w4gl(stage, name, encode_source_w4gl(component))
            write_component_wml(stage, name, component.markup)
            write_component_defaults(
                stage / f"{name}.w4gl",
                component.props.get("fielddefaults", {}),
                writer=writer,
            )
        except (
            ProjectError,
            ValueError,
            TypeError,
            KeyError,
            etree.XMLSyntaxError,
        ) as ex:
            raise ComponentProjectionError(str(ex)) from ex
        for suffix in (
            ".w4gl",
            ".wml",
            ".fielddefaults.json",
            ".queries.json",
            ".icons.json",
        ):
            target = source_dir / f"{name}{suffix}"
            source = stage / target.name
            if source.exists():
                normalize_case_path(target, progress=progress, label="component")
                copy2(source, target)
            else:
                target.unlink(missing_ok=True)
        defaults = stage.parent / "field_defaults.json"
        if defaults.exists() and not (source_dir.parent / defaults.name).exists():
            copy2(defaults, source_dir.parent / defaults.name)
        return component


def export_component_to_paths(
    connection: OpenRoadConnection,
    app: str,
    component: str,
    paths: ComponentExportPaths,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Export one component XML and encode the component named inside that XML."""

    previous = paths.xml_path.read_bytes() if paths.xml_path.exists() else None
    try:
        return _export_component_to_paths(connection, app, component, paths, progress)
    except Exception:
        if paths.xml_path.exists() and paths.xml_path.read_bytes() != previous:
            archive = paths.xml_path.parent / "export-errors" / uuid4().hex
            archive.mkdir(parents=True)
            copy2(paths.xml_path, archive / paths.xml_path.name)
        if previous is None:
            paths.xml_path.unlink(missing_ok=True)
        else:
            paths.xml_path.write_bytes(previous)
        raise


def _export_component_to_paths(
    connection: OpenRoadConnection,
    app: str,
    component: str,
    paths: ComponentExportPaths,
    progress: Callable[[str], None] | None,
) -> Path:
    paths.xml_path.parent.mkdir(parents=True, exist_ok=True)
    paths.w4gl_path.parent.mkdir(parents=True, exist_ok=True)
    backup_component_xml(connection, app, component, paths.xml_path)

    from .portable_source import read_document

    tree = read_document(paths.xml_path)
    if tree.tag != "OPENROAD" or len(tree) != 1 or tree[0].tag != "COMPONENT":
        raise ProjectError("Expected a single exported component")
    from .image_assets import AssetWriter

    writer = AssetWriter(paths.w4gl_path.parent)
    parsed_component = project_component_files(
        tree[0], paths.w4gl_path.parent, writer, progress
    )
    normalize_component_xml_path(paths.xml_path, parsed_component.name)
    return paths.w4gl_path.parent / f"{parsed_component.name}.w4gl"


def apply_field_default_inheritance(
    root: Path,
    app: str,
    components: list[Component],
    *,
    source_nodes: list[etree._Element] | None = None,
) -> None:
    """Project native stylesheets independently from explicit field state."""
    from . import native_styles

    native = {node.get("name"): node for node in source_nodes or []}
    frames = [c for c in components if c.type in FRAME_COMPONENT_TYPES]
    if not frames:
        return
    parent = native_styles.parent_styles(root / app)
    projected = []
    for component in frames:
        node = native.get(component.name)
        if node is None:
            raise ProjectError("Native stylesheet export requires authoritative XML")
        stylesheet = node.find("fielddefaults")
        if native_styles.is_absent(stylesheet):
            delta = {"absent": True}
        else:
            assert stylesheet is not None
            delta = native_styles.difference(parent, native_styles.encode(stylesheet))
        markup = encode_frame_markup(
            [child for child in node if child.tag in FRAME_MARKUP_CHILDREN],
            {},
            explicit=True,
        )
        projected.append((component, delta, markup))
    if not (root / "field_defaults.json").exists():
        write_json(root / "field_defaults.json", native_styles.empty_delta())
    for component, delta, markup in projected:
        component.props["fielddefaults"] = delta
        component.markup = markup


def backup_application_xml(
    connection: OpenRoadConnection,
    app: str,
    xml_path: Path,
) -> None:
    """Run the correct backend-specific full application XML export."""

    validate_source_route(connection)

    if connection.backend == "local":
        if connection.revision_generation:
            local.backup_application(
                connection.vnode,
                connection.database,
                app,
                xml_path,
                run_cmd=lambda command, input_text: local.run_subprocess(
                    local_writer_command(
                        command, connection.database, connection.writer_encoding
                    ),
                    input_text,
                ),
            )
            return
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

    validate_source_route(connection)

    if connection.backend == "local":
        if connection.revision_generation:
            local.backup_component(
                connection.vnode,
                connection.database,
                app,
                component,
                xml_path,
                run_cmd=lambda command, input_text: local.run_subprocess(
                    local_writer_command(
                        command, connection.database, connection.writer_encoding
                    ),
                    input_text,
                ),
            )
            return
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


def canonical_application_name(
    connection: OpenRoadConnection,
    root: Path,
    app: str,
) -> str:
    """Resolve a case-insensitive app request to the database/project casing."""

    try:
        return read_application(connection, app).name
    except (LocalCommandError, RemoteCommandError, OSError):
        pass

    for path in root.iterdir():
        if path.is_dir() and path.name.lower() == app.lower():
            return path.name

    return app


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


def read_component_sync_metadata(
    connection: OpenRoadConnection,
    app: str,
) -> list[database_module.ComponentSyncMetadata]:
    sql_backend = connection_sql_backend(connection)
    if sql_backend == "odbc":
        return odbc_get_component_sync_metadata(require_odbc_settings(connection), app)
    if sql_backend == "local":
        return local_get_component_sync_metadata(
            connection.vnode,
            connection.database,
            app,
        )

    metadata = read_all_component_sync_metadata(connection)
    return [item for item in metadata if item.application_name.lower() == app.lower()]


def read_all_component_sync_metadata(
    connection: OpenRoadConnection,
) -> list[database_module.ComponentSyncMetadata]:
    sql_backend = connection_sql_backend(connection)
    if sql_backend == "odbc":
        return odbc_get_all_component_sync_metadata(require_odbc_settings(connection))
    if sql_backend == "local":
        return local_get_all_component_sync_metadata(
            connection.vnode, connection.database
        )

    return get_all_component_sync_metadata(
        remote=require_remote_host(connection),
        vnode=connection.vnode,
        database=connection.database,
    )


def record_component_sync_metadata(
    connection: OpenRoadConnection,
    root: Path,
    app: str,
) -> None:
    """Store current change metadata for future syncs."""

    update_component_entries(root, read_component_sync_metadata(connection, app))


def record_component_sync_metadata_best_effort(
    connection: OpenRoadConnection,
    root: Path,
    app: str,
    progress: Callable[[str], None] | None,
) -> None:
    """Record sync metadata without failing a successful export."""

    try:
        record_component_sync_metadata(connection, root, app)
    except odbc_error_types(LocalCommandError, RemoteCommandError, OSError):
        progress_message(
            progress,
            "WARNING: Export succeeded, but sync metadata could not be recorded. "
            "Run gorak sync later to refresh local state.",
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


def normalize_application_paths(
    root: Path,
    app: str,
    progress: Callable[[str], None] | None = None,
) -> None:
    """Rename existing app/cache directories to match database casing."""

    normalize_case_path(root / app, progress=progress, label="application")
    cache_dir = normalize_case_path(root / ".openroad" / app, disposable=True)
    normalize_case_path(cache_dir / f"{app}.xml", disposable=True)


def normalize_component_xml_path(xml_path: Path, component_name: str) -> Path:
    """Rename cached component XML to match the component name from XML."""

    target = xml_path.parent / f"{component_name}.xml"
    if target.name.lower() != xml_path.name.lower():
        return xml_path
    return normalize_case_path(target, fallback=xml_path, disposable=True)


def normalize_case_path(
    path: Path,
    fallback: Path | None = None,
    disposable: bool = False,
    progress: Callable[[str], None] | None = None,
    label: str = "path",
) -> Path:
    """Rename a same-name-different-case path to `path` when present."""

    source = fallback if fallback is not None and fallback.exists() else None
    variants = case_variants(path)
    exact = [child for child in variants if child.name == path.name]
    others = [child for child in variants if child.name != path.name]

    if source is not None:
        source = next((child for child in others if child.name == source.name), source)
        if source.name != path.name and exact:
            if disposable:
                remove_paths(exact)
            else:
                raise ProjectError(f"Case-conflicting paths exist: {source} and {path}")

    if source is None:
        if exact and others:
            if disposable:
                remove_paths(others)
                return path
            raise ProjectError(f"Case-conflicting paths exist for: {path}")
        if exact:
            return path
        if len(others) > 1:
            if disposable:
                remove_paths(others)
                return path
            raise ProjectError(f"Case-conflicting paths exist for: {path}")
        source = others[0] if others else None

    if source is None or source.name == path.name:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".gorak-case-rename-{uuid4().hex}"
    source.rename(temp_path)
    temp_path.rename(path)
    progress_message(
        progress, f"Corrected {label} casing: {source.name} -> {path.name}"
    )
    return path


def case_variants(path: Path) -> list[Path]:
    parent = path.parent
    if not parent.is_dir():
        return []

    return [
        child for child in parent.iterdir() if child.name.lower() == path.name.lower()
    ]


def remove_paths(paths: list[Path]) -> None:
    for path in paths:
        remove_path(path)


def remove_path(path: Path) -> None:
    if path.is_dir():
        rmtree(path)
    elif path.exists():
        path.unlink()


def progress_message(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def write_component_w4gl(
    source_dir: Path,
    component_name: str,
    content: str,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Write a component using the OpenROAD XML name as the source filename."""

    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / f"{component_name}.w4gl"
    normalize_case_path(path, progress=progress, label="component")
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def write_component_wml(
    source_dir: Path,
    component_name: str,
    content: str | None,
    progress: Callable[[str], None] | None = None,
) -> Path | None:
    """Write frame markup when a component has a visual source tree."""

    if content is None:
        return None

    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / f"{component_name}.wml"
    normalize_case_path(path, progress=progress, label="component")
    path.write_text(content.rstrip("\n") + "\n", encoding="utf-8", newline="\n")
    return path

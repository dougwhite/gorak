import argparse
import csv
import io
import json
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from lxml import etree

from .domain import Application, ComponentInfo
from .parser import encode_w4gl, parse_xml
from .project import (
    GorakContext,
    ProjectError,
    configure_remote,
    create_project,
    load_context,
    load_project,
)
from .remote import (
    RemoteHost,
    backup_component,
    download_file,
    get_app_list,
    get_component_list,
)


@dataclass(frozen=True)
class OpenRoadConnection:
    backend: str
    vnode: str
    database: str
    remote_host: RemoteHost


@dataclass(frozen=True)
class ComponentExportPaths:
    xml_path: Path
    w4gl_path: Path


def encode_xml_file(xml_path: str) -> str:
    """Parses an OpenROAD XML export and returns encoded .w4gl text."""

    xml = etree.parse(xml_path)
    component = parse_xml(xml)
    return encode_w4gl(component)


def build_parser() -> argparse.ArgumentParser:
    """Builds the gorak CLI argument parser."""

    parser = argparse.ArgumentParser(prog="gorak")
    subparsers = parser.add_subparsers(dest="command")

    new_parser = subparsers.add_parser("new")
    new_parser.add_argument("name")

    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(dest="config_command")

    remote_config = config_subparsers.add_parser("remote")
    remote_config.add_argument("--host", required=True)
    remote_config.add_argument("--user", required=True)
    remote_config.add_argument("--gorak-root", required=True)
    remote_config.add_argument("--vnode", required=True)
    remote_config.add_argument("--database", required=True)

    encode_parser = subparsers.add_parser("encode")
    encode_parser.add_argument("xml_file")
    encode_parser.add_argument("--output")

    app_parser = subparsers.add_parser("app")
    app_subparsers = app_parser.add_subparsers(dest="app_command")

    app_list = app_subparsers.add_parser("list")
    add_openroad_connection_args(app_list)
    app_list.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
    )

    component_parser = subparsers.add_parser("component")
    component_subparsers = component_parser.add_subparsers(dest="component_command")

    component_list = component_subparsers.add_parser("list")
    add_openroad_connection_args(component_list)
    component_list.add_argument("app")
    component_list.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
    )

    export_component = component_subparsers.add_parser("export")
    add_openroad_connection_args(export_component)
    export_component.add_argument("app")
    export_component.add_argument("component")
    export_component.add_argument("--output")

    return parser


def add_openroad_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--user")
    parser.add_argument("--host")
    parser.add_argument("--gorak-root")
    parser.add_argument("--vnode")
    parser.add_argument("--database")


def new_command(args: argparse.Namespace) -> str:
    """Creates a new gorak project."""

    context = load_context(Path.cwd())
    if context.project is not None:
        raise ProjectError(
            f"Cannot create a gorak project inside existing project: {context.project.root}"
        )

    name = cast(str, args.name)
    project = create_project(Path(name))
    return str(project.root)


def encode_command(args: argparse.Namespace) -> str:
    """Encodes an OpenROAD XML export to .w4gl text."""

    xml_file = cast(str, args.xml_file)
    output_path = cast(str | None, args.output)
    output = encode_xml_file(xml_file)
    if output_path is None:
        return output

    with open(output_path, "w") as file:
        file.write(output)
    return output_path


def config_remote_command(args: argparse.Namespace) -> str:
    """Configures remote OpenROAD access for the current project."""

    project = load_project(Path.cwd())
    env_path = configure_remote(
        project=project,
        host=cast(str, args.host),
        user=cast(str, args.user),
        gorak_root=cast(str, args.gorak_root),
        vnode=cast(str, args.vnode),
        database=cast(str, args.database),
    )
    return str(env_path)


def resolve_openroad_connection(
    args: argparse.Namespace, context: GorakContext
) -> OpenRoadConnection:
    env = context.env
    backend = env_value(args, "backend", env, "GORAK_BACKEND") or "remote"
    if backend != "remote":
        raise ProjectError(f"OpenROAD backend is not implemented: {backend}")

    values = {
        "user": env_value(args, "user", env, "GORAK_REMOTE_USER"),
        "host": env_value(args, "host", env, "GORAK_REMOTE_HOST"),
        "gorak_root": env_value(args, "gorak_root", env, "GORAK_REMOTE_ROOT"),
        "vnode": env_value(args, "vnode", env, "GORAK_VNODE"),
        "database": env_value(args, "database", env, "GORAK_DATABASE"),
    }
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise ProjectError(
            "Missing OpenROAD connection settings: "
            + ", ".join(connection_hint(key) for key in missing)
        )

    return OpenRoadConnection(
        backend=backend,
        vnode=cast(str, values["vnode"]),
        database=cast(str, values["database"]),
        remote_host=RemoteHost(
            user=cast(str, values["user"]),
            host=cast(str, values["host"]),
            gorak_root=cast(str, values["gorak_root"]),
        ),
    )


def env_value(
    args: argparse.Namespace,
    arg_name: str,
    env: dict[str, str],
    env_name: str,
) -> str | None:
    value = getattr(args, arg_name, None)
    if value:
        return cast(str, value)
    return env.get(env_name)


def connection_hint(key: str) -> str:
    hints = {
        "user": "--user/GORAK_REMOTE_USER",
        "host": "--host/GORAK_REMOTE_HOST",
        "gorak_root": "--gorak-root/GORAK_REMOTE_ROOT",
        "vnode": "--vnode/GORAK_VNODE",
        "database": "--database/GORAK_DATABASE",
    }
    return hints[key]


def export_component_command(args: argparse.Namespace) -> str:
    """Exports an OpenROAD component to local .w4gl source."""

    context = load_context(Path.cwd())
    output_path = cast(str | None, args.output)
    if context.project is None and output_path is None:
        raise ProjectError("--output is required outside a gorak project")
    if context.project is not None and output_path is not None:
        raise ProjectError("--output is only supported outside a gorak project")

    connection = resolve_openroad_connection(args, context)
    app = cast(str, args.app)
    component = cast(str, args.component)
    remote_xml_path = backup_component(
        remote=connection.remote_host,
        vnode=connection.vnode,
        database=connection.database,
        app=app,
        component=component,
    )

    if context.project is None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = ComponentExportPaths(
                xml_path=Path(temp_dir) / f"{component}.xml",
                w4gl_path=Path(cast(str, output_path)),
            )
            export_component_to_paths(connection, remote_xml_path, paths)
            return str(paths.w4gl_path)

    paths = resolve_project_component_export_paths(context, app, component)
    export_component_to_paths(connection, remote_xml_path, paths)
    return str(paths.w4gl_path)


def resolve_project_component_export_paths(
    context: GorakContext,
    app: str,
    component: str,
) -> ComponentExportPaths:
    if context.project is None:
        raise ProjectError("Component export requires a gorak project")

    return ComponentExportPaths(
        xml_path=context.project.root / ".openroad" / app / f"{component}.xml",
        w4gl_path=context.project.root / app / f"{component}.w4gl",
    )


def export_component_to_paths(
    connection: OpenRoadConnection,
    remote_xml_path: str,
    paths: ComponentExportPaths,
) -> None:
    paths.xml_path.parent.mkdir(parents=True, exist_ok=True)
    paths.w4gl_path.parent.mkdir(parents=True, exist_ok=True)
    download_file(
        remote=connection.remote_host,
        remote_path=remote_xml_path,
        local_path=str(paths.xml_path),
    )
    paths.w4gl_path.write_text(encode_xml_file(str(paths.xml_path)))


def applications_to_json(applications: list[Application]) -> str:
    """Format applications as JSON."""

    return json.dumps([asdict(app) for app in applications], indent=2)


def applications_to_csv(applications: list[Application]) -> str:
    """Format applications as CSV."""

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["name", "start_component", "description"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(asdict(app) for app in applications)

    return output.getvalue().rstrip("\n")


def components_to_json(components: list[ComponentInfo]) -> str:
    """Format components as JSON."""

    return json.dumps([asdict(component) for component in components], indent=2)


def components_to_csv(components: list[ComponentInfo]) -> str:
    """Format components as CSV."""

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["application_name", "name", "type", "description"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(asdict(component) for component in components)

    return output.getvalue().rstrip("\n")


def app_list_command(args: argparse.Namespace) -> str:
    """Reads remote OpenROAD applications and formats them for stdout."""

    connection = resolve_openroad_connection(args, load_context(Path.cwd()))
    applications = get_app_list(
        remote=connection.remote_host,
        vnode=connection.vnode,
        database=connection.database,
    )

    if cast(str, args.format) == "csv":
        return applications_to_csv(applications)

    return applications_to_json(applications)


def component_list_command(args: argparse.Namespace) -> str:
    """Reads OpenROAD component metadata and formats it for stdout."""

    connection = resolve_openroad_connection(args, load_context(Path.cwd()))
    components = get_component_list(
        remote=connection.remote_host,
        vnode=connection.vnode,
        database=connection.database,
        app=cast(str, args.app),
    )

    if cast(str, args.format) == "csv":
        return components_to_csv(components)

    return components_to_json(components)


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)

    parser = build_parser()
    parsed = parser.parse_args(args)

    try:
        if parsed.command == "new":
            print(new_command(parsed))
            return

        if parsed.command == "config" and parsed.config_command == "remote":
            print(config_remote_command(parsed))
            return

        if parsed.command == "encode":
            print(encode_command(parsed))
            return

        if parsed.command == "app" and parsed.app_command == "list":
            print(app_list_command(parsed))
            return

        if parsed.command == "component" and parsed.component_command == "list":
            print(component_list_command(parsed))
            return

        if parsed.command == "component" and parsed.component_command == "export":
            print(export_component_command(parsed))
            return
    except ProjectError as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        raise SystemExit(1) from ex

    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()

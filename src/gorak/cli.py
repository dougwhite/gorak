import argparse
import csv
import io
import json
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import asdict
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import cast

from .connection import (
    connection_source,
    resolve_openroad_connection,
    resolve_remote_host,
)
from .domain import Application, ComponentInfo
from .export import (
    component_export_paths,
    encode_xml_file,
    export_component,
    export_component_to_paths,
    read_application,
    read_applications,
    read_components,
    write_app_metadata,
)
from .project import (
    ProjectError,
    configure_remote,
    create_project,
    load_context,
    load_project,
)
from .remote import (
    RemoteHost,
    install_remote_helpers,
)

REMOTE_SCRIPT_PACKAGE = "gorak.remote_scripts"


def build_parser() -> argparse.ArgumentParser:
    """Builds the gorak CLI argument parser."""

    parser = argparse.ArgumentParser(prog="gorak")
    subparsers = parser.add_subparsers(dest="command")

    new_parser = subparsers.add_parser("new")
    new_parser.add_argument("--nogit", action="store_true")
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

    remote_parser = subparsers.add_parser("remote")
    remote_subparsers = remote_parser.add_subparsers(dest="remote_command")

    remote_install = remote_subparsers.add_parser("install")
    add_remote_host_args(remote_install)

    app_parser = subparsers.add_parser("app")
    app_subparsers = app_parser.add_subparsers(dest="app_command")

    app_list = app_subparsers.add_parser("list")
    add_openroad_connection_args(app_list)
    app_list.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
    )

    app_export = app_subparsers.add_parser("export")
    add_openroad_connection_args(app_export)
    app_export.add_argument("app")
    app_export.add_argument("--output")

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
    parser.add_argument("--backend", choices=["remote", "local"])
    add_remote_host_args(parser)
    parser.add_argument("--vnode")
    parser.add_argument("--database")


def add_remote_host_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--user")
    parser.add_argument("--host")
    parser.add_argument("--gorak-root")


def new_command(args: argparse.Namespace) -> str:
    """Creates a new gorak project."""

    context = load_context(Path.cwd())
    if context.project is not None:
        raise ProjectError(
            f"Cannot create a gorak project inside existing project: {context.project.root}"
        )

    name = cast(str, args.name)
    project = create_project(Path(name), init_repo=not cast(bool, args.nogit))
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


def remote_install_command(args: argparse.Namespace) -> str:
    """Installs Windows SSH helper files to the remote gorak root."""

    remote = resolve_remote_host(args, load_context(Path.cwd()))
    copied = install_packaged_remote_helpers(remote)
    file_label = "file" if len(copied) == 1 else "files"
    return (
        f"Installed {len(copied)} {file_label} "
        f"to {remote.ssh_target}:{remote.gorak_root}"
    )


def install_packaged_remote_helpers(remote: RemoteHost) -> list[str]:
    """Installs packaged Windows SSH helper files to the remote host."""

    with ExitStack() as stack:
        helper_files = [
            stack.enter_context(as_file(resource))
            for resource in remote_script_resources()
        ]
        return install_remote_helpers(remote, helper_files)


def remote_script_resources() -> list[Traversable]:
    return sorted(
        (
            resource
            for resource in files(REMOTE_SCRIPT_PACKAGE).iterdir()
            if resource.is_file() and resource.name != "__init__.py"
        ),
        key=lambda resource: resource.name,
    )


def export_component_command(args: argparse.Namespace) -> str:
    """Exports an OpenROAD component to local .w4gl source."""

    context = load_context(Path.cwd())
    connection = resolve_openroad_connection(args, context)
    path = export_component(
        connection=connection,
        context=context,
        app=cast(str, args.app),
        component=cast(str, args.component),
        output_path=cast(str | None, args.output),
    )
    return str(path)


def app_export_command(args: argparse.Namespace) -> str:
    """Exports all components in one OpenROAD application."""

    context = load_context(Path.cwd())
    output_path = cast(str | None, args.output)
    if context.project is None and output_path is None:
        raise ProjectError("--output is required outside a gorak project")
    if context.project is not None and output_path is not None:
        raise ProjectError("--output is only supported outside a gorak project")

    connection = resolve_openroad_connection(args, context)
    app = cast(str, args.app)
    root = (
        context.project.root
        if context.project is not None
        else Path(cast(str, output_path))
    )
    print(f"Exporting application {app} from {connection_source(connection)}")
    print("Retrieving application metadata")
    application = read_application(connection, app)
    write_app_metadata(root, application)
    print("Retrieving component list")
    components = read_components(connection, app)
    for component in components:
        print(f"Exporting component {app}::{component.name}")
        export_component_to_paths(
            connection=connection,
            app=app,
            component=component.name,
            paths=component_export_paths(root, app, component.name),
        )

    return "Export complete"


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
    """Reads OpenROAD applications and formats them for stdout."""

    connection = resolve_openroad_connection(args, load_context(Path.cwd()))
    applications = read_applications(connection)

    if cast(str, args.format) == "csv":
        return applications_to_csv(applications)

    return applications_to_json(applications)


def component_list_command(args: argparse.Namespace) -> str:
    """Reads OpenROAD component metadata and formats it for stdout."""

    connection = resolve_openroad_connection(args, load_context(Path.cwd()))
    components = read_components(connection, cast(str, args.app))

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

        if parsed.command == "remote" and parsed.remote_command == "install":
            print(remote_install_command(parsed))
            return

        if parsed.command == "app" and parsed.app_command == "list":
            print(app_list_command(parsed))
            return

        if parsed.command == "app" and parsed.app_command == "export":
            print(app_export_command(parsed))
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

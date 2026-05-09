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

from .audit import (
    audit_project_xml,
    audit_xml_file,
    filter_missing_only,
    filter_reports_missing_only,
)
from .connection import (
    connection_source,
    resolve_openroad_connection,
    resolve_remote_host,
)
from .domain import Application, ComponentInfo, IncludedApplication
from .export import (
    encode_xml_file,
    export_application,
    export_component,
    read_applications,
    read_components,
    read_includes,
)
from .field_defaults import flatten_app_defaults
from .project import (
    ProjectError,
    configure_project,
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
    add_config_args(config_parser, require_values=False)
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

    includes_parser = subparsers.add_parser("includes")
    includes_subparsers = includes_parser.add_subparsers(dest="includes_command")

    includes_list = includes_subparsers.add_parser("list")
    add_openroad_connection_args(includes_list)
    includes_list.add_argument("app")

    defaults_parser = subparsers.add_parser("defaults")
    defaults_subparsers = defaults_parser.add_subparsers(dest="defaults_command")
    defaults_subparsers.add_parser("flatten")

    debug_parser = subparsers.add_parser("debug")
    debug_subparsers = debug_parser.add_subparsers(dest="debug_command")

    debug_audit = debug_subparsers.add_parser("audit")
    debug_audit.add_argument("xml_file", nargs="?")
    debug_audit.add_argument("--all", action="store_true")
    debug_audit.add_argument("--missing-only", action="store_true")

    return parser


def add_openroad_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", choices=["remote", "local"])
    parser.add_argument("--sql-backend", choices=["remote", "local", "odbc"])
    add_remote_host_args(parser)
    parser.add_argument("--vnode")
    parser.add_argument("--database")
    parser.add_argument("--db-driver")
    parser.add_argument("--db-host")
    parser.add_argument("--db-listen-address")
    parser.add_argument("--db-database")
    parser.add_argument("--db-user")
    parser.add_argument("--db-password")


def add_config_args(parser: argparse.ArgumentParser, require_values: bool) -> None:
    parser.add_argument("--backend", choices=["remote", "local"], required=require_values)
    parser.add_argument(
        "--sql-backend",
        choices=["remote", "local", "odbc"],
    )
    parser.add_argument("--vnode", required=require_values)
    parser.add_argument("--database", required=require_values)
    parser.add_argument("--host")
    parser.add_argument("--user")
    parser.add_argument("--gorak-root")
    parser.add_argument("--db-driver")
    parser.add_argument("--db-host")
    parser.add_argument("--db-listen-address")
    parser.add_argument("--db-database")
    parser.add_argument("--db-user")
    parser.add_argument("--db-password")


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
    """Configures OpenROAD access for the current project."""

    validate_config_args(args)
    project = load_project(Path.cwd())
    env_path = configure_project(
        project=project,
        backend="remote" if args.config_command == "remote" else cast(str, args.backend),
        vnode=cast(str, args.vnode),
        database=cast(str, args.database),
        host=cast(str | None, args.host),
        user=cast(str | None, args.user),
        gorak_root=cast(str | None, args.gorak_root),
        sql_backend=cast(str | None, args.sql_backend),
        db_driver=cast(str | None, args.db_driver),
        db_host=cast(str | None, args.db_host),
        db_listen_address=cast(str | None, args.db_listen_address),
        db_database=cast(str | None, args.db_database),
        db_user=cast(str | None, args.db_user),
        db_password=cast(str | None, args.db_password),
    )
    return str(env_path)


def validate_config_args(args: argparse.Namespace) -> None:
    required = {
        "backend": "--backend",
        "vnode": "--vnode/GORAK_VNODE",
        "database": "--database/GORAK_DATABASE",
    }
    if args.config_command == "remote":
        required = {
            "host": "--host/GORAK_REMOTE_HOST",
            "user": "--user/GORAK_REMOTE_USER",
            "gorak_root": "--gorak-root/GORAK_REMOTE_ROOT",
            "vnode": "--vnode/GORAK_VNODE",
            "database": "--database/GORAK_DATABASE",
        }

    missing = [hint for name, hint in required.items() if not getattr(args, name, None)]

    backend = "remote" if args.config_command == "remote" else args.backend
    sql_backend = getattr(args, "sql_backend", None)
    if backend == "remote" or sql_backend == "remote":
        for name, hint in [
            ("host", "--host/GORAK_REMOTE_HOST"),
            ("user", "--user/GORAK_REMOTE_USER"),
            ("gorak_root", "--gorak-root/GORAK_REMOTE_ROOT"),
        ]:
            if not getattr(args, name, None) and hint not in missing:
                missing.append(hint)

    if sql_backend == "odbc":
        for name, hint in [
            ("db_driver", "--db-driver/GORAK_DB_DRIVER"),
            ("db_host", "--db-host/GORAK_DB_HOST"),
            ("db_listen_address", "--db-listen-address/GORAK_DB_LISTEN_ADDRESS"),
            ("db_user", "--db-user/GORAK_DB_USER"),
            ("db_password", "--db-password/GORAK_DB_PASSWORD"),
        ]:
            if not getattr(args, name, None):
                missing.append(hint)

    if missing:
        raise ProjectError("Missing config settings: " + ", ".join(missing))


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
    connection = resolve_openroad_connection(args, context)
    app = cast(str, args.app)
    print(f"Exporting application {app} from {connection_source(connection)}")
    export_application(
        connection=connection,
        context=context,
        app=app,
        output_path=cast(str | None, args.output),
        progress=print,
    )

    return "Export complete"


def applications_to_json(applications: list[Application]) -> str:
    """Format applications as JSON."""

    return json.dumps([application_to_dict(app) for app in applications], indent=2)


def application_to_dict(application: Application) -> dict[str, str]:
    """Format application metadata, omitting optional blank values."""

    data = asdict(application)
    return {
        key: value
        for key, value in data.items()
        if key not in {"database_name", "database_type"} or value
    }


def applications_to_csv(applications: list[Application]) -> str:
    """Format applications as CSV."""

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["name", "start_component", "description"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(application_to_dict(app) for app in applications)

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


def includes_to_json(includes: list[IncludedApplication]) -> str:
    """Format included application metadata as JSON."""

    return json.dumps(includes, indent=2)


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


def includes_list_command(args: argparse.Namespace) -> str:
    """Reads included application metadata and formats it for stdout."""

    connection = resolve_openroad_connection(args, load_context(Path.cwd()))
    return includes_to_json(read_includes(connection, cast(str, args.app)))


def defaults_flatten_command(args: argparse.Namespace) -> str:
    """Flatten shared app-level field defaults into the project defaults."""

    project = load_project(Path.cwd())
    result = flatten_app_defaults(project.root)
    value_label = "value" if result.promoted_values == 1 else "values"
    app_label = "application" if result.app_count == 1 else "applications"
    return (
        f"Flattened {result.promoted_values} field default {value_label} "
        f"across {result.app_count} {app_label}"
    )


def debug_audit_command(args: argparse.Namespace) -> str:
    """Audit what an XML export does not currently represent in source files."""

    audit_all = cast(bool, args.all)
    xml_file = cast(str | None, args.xml_file)
    if audit_all and xml_file is not None:
        raise ProjectError("Use either --all or XML_FILE, not both")
    if audit_all:
        project = load_project(Path.cwd())
        reports = audit_project_xml(project.root)
        if cast(bool, args.missing_only):
            reports = filter_reports_missing_only(reports)
        return json.dumps(reports, indent=2)
    if xml_file is None:
        raise ProjectError("Missing XML_FILE or --all")

    report = audit_xml_file(xml_file)
    if cast(bool, args.missing_only):
        report = filter_missing_only(report) or {
            "path": xml_file,
            "application": None,
            "components": [],
        }
    return json.dumps(report, indent=2)


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)

    parser = build_parser()
    parsed = parser.parse_args(args)

    try:
        if parsed.command == "new":
            print(new_command(parsed))
            return

        if parsed.command == "config":
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

        if parsed.command == "includes" and parsed.includes_command == "list":
            print(includes_list_command(parsed))
            return

        if parsed.command == "defaults" and parsed.defaults_command == "flatten":
            print(defaults_flatten_command(parsed))
            return

        if parsed.command == "debug" and parsed.debug_command == "audit":
            print(debug_audit_command(parsed))
            return
    except ProjectError as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        raise SystemExit(1) from ex

    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()

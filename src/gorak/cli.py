import argparse
import csv
import io
import json
import subprocess
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import asdict
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import cast
from uuid import uuid4

import pyodbc
from sqlalchemy.exc import SQLAlchemyError

from .app_scaffold import create_application
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
from .domain import Application, ApplicationExport, ComponentInfo, IncludedApplication
from .export import (
    application_export_paths,
    encode_xml_file,
    export_application,
    export_component,
    export_root,
    read_applications,
    read_components,
    read_includes,
)
from .field_defaults import flatten_app_defaults
from .importer import import_component
from .local import LocalCommandError
from .project import (
    ProjectError,
    configure_project,
    create_project,
    load_context,
    load_project,
)
from .project_lock import locked_command
from .remote import (
    RemoteCommandError,
    RemoteHost,
    install_remote_helpers,
    verify_remote_helpers,
)
from .run_backend import execute_application
from .runner import TestApplication, report_summary, test_applications
from .safe_pull import sync_project

REMOTE_SCRIPT_PACKAGE = "gorak.remote_scripts"


def build_parser() -> argparse.ArgumentParser:
    """Builds the gorak CLI argument parser."""

    parser = argparse.ArgumentParser(prog="gorak")
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install")
    install_action = install_parser.add_mutually_exclusive_group()
    install_action.add_argument(
        "--export-sql",
        metavar="PATH",
        help="Write DBA-reviewed source tracking SQL; use - for stdout",
    )

    install_action.add_argument(
        "--check", action="store_true", help="Check tracking inventory via ODBC"
    )
    install_parser.add_argument(
        "--upgrade", action="store_true", help="Upgrade tracking schema v1 to v2"
    )
    add_openroad_connection_args(install_parser)

    journal_parser = subparsers.add_parser(
        "journal", help="Preview pending source journal events"
    )
    journal_parser.add_argument("--limit", type=int, default=100)
    journal_parser.add_argument(
        "--rebootstrap",
        action="store_true",
        help="Rebuild journal observations with a fresh consumer and full exports",
    )
    journal_parser.add_argument(
        "--verify-selective",
        action="store_true",
        help="Verify selective snapshots against full exports",
    )
    journal_parser.add_argument(
        "--map", action="store_true", help="Show affected application candidates"
    )
    journal_parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Compare source and acknowledge verified events",
    )
    add_openroad_connection_args(journal_parser)

    recovery_parser = subparsers.add_parser("recover")
    recovery_parser.add_argument("operation", choices=["push"])
    add_openroad_connection_args(recovery_parser)

    new_parser = subparsers.add_parser("new")
    new_parser.add_argument("--nogit", action="store_true")
    new_parser.add_argument("name")
    new_parser.add_argument("application_name", nargs="?")
    new_parser.add_argument("--test", action="store_true")

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

    remote_check = remote_subparsers.add_parser("check")
    add_remote_host_args(remote_check)

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

    component_import = component_subparsers.add_parser("import")
    add_openroad_connection_args(component_import)
    component_import.add_argument("app")
    component_import.add_argument("component")
    component_import.add_argument("--dry-run", action="store_true")

    includes_parser = subparsers.add_parser("includes")
    includes_subparsers = includes_parser.add_subparsers(dest="includes_command")

    includes_list = includes_subparsers.add_parser("list")
    add_openroad_connection_args(includes_list)
    includes_list.add_argument("app")

    defaults_parser = subparsers.add_parser("defaults")
    defaults_subparsers = defaults_parser.add_subparsers(dest="defaults_command")
    defaults_subparsers.add_parser("flatten")

    status_parser = subparsers.add_parser("status")
    add_openroad_connection_args(status_parser)

    sync_parser = subparsers.add_parser("sync")
    add_openroad_connection_args(sync_parser)
    sync_parser.add_argument(
        "--bind",
        action="store_true",
        help="Verify and bind an existing cache to its configured target",
    )
    sync_parser.add_argument("--push", action="store_true", help="Import disk changes")
    sync_parser.add_argument(
        "--dry-run", action="store_true", help="Prepare push XML without importing"
    )

    debug_parser = subparsers.add_parser("debug")
    debug_subparsers = debug_parser.add_subparsers(dest="debug_command")

    debug_audit = debug_subparsers.add_parser("audit")
    debug_audit.add_argument("xml_file", nargs="?")
    debug_audit.add_argument("--all", action="store_true")
    debug_audit.add_argument("--missing-only", action="store_true")

    for name in ["run", "test"]:
        run_parser = subparsers.add_parser(name)
        add_openroad_connection_args(run_parser)
        if name == "run":
            run_parser.add_argument("app")
        else:
            run_parser.add_argument("--app")
        run_parser.add_argument("--component")
        run_parser.add_argument("--timeout", type=int)
        run_parser.add_argument("--trace", action="store_true")
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
    parser.add_argument(
        "--backend", choices=["remote", "local"], required=require_values
    )
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


@locked_command
def new_command(args: argparse.Namespace) -> str:
    """Create a project, or an application inside the current project."""

    if args.application_name is not None:
        if args.name != "app" or args.nogit:
            raise ProjectError(
                "Use gorak new app NAME [--test] to scaffold an application"
            )
        project = load_project(Path.cwd())
        path = create_application(project, args.application_name, test=args.test)
        return f"Created {path} (disk only; starting component and includes are not configured)"
    if args.test:
        raise ProjectError("--test requires gorak new app NAME")
    context = load_context(Path.cwd())
    if context.project is not None:
        raise ProjectError(
            f"Cannot create a gorak project inside existing project: {context.project.root}"
        )

    name = cast(str, args.name)
    project = create_project(Path(name), init_repo=not cast(bool, args.nogit))
    return str(project.root)


@locked_command
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


@locked_command
def config_remote_command(args: argparse.Namespace) -> str:
    """Configures OpenROAD access for the current project."""

    validate_config_args(args)
    project = load_project(Path.cwd())
    env_path = configure_project(
        project=project,
        backend="remote"
        if args.config_command == "remote"
        else cast(str, args.backend),
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


def remote_check_command(args: argparse.Namespace) -> str:
    """Checks whether Windows SSH helper files are installed and current."""

    remote = resolve_remote_host(args, load_context(Path.cwd()))
    verify_remote_helpers(remote)
    return f"Remote helpers OK on {remote.ssh_target}:{remote.gorak_root}"


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


@locked_command
def export_component_command(args: argparse.Namespace) -> str:
    """Exports an OpenROAD component to local .w4gl source."""

    context = load_context(Path.cwd())
    connection = resolve_openroad_connection(args, context)
    from .sync_guard import binding_status

    if context.project is not None:
        binding_status(connection, context.project.root)
    app = cast(str, args.app)
    component = cast(str, args.component)
    print(
        f"Exporting component {app}::{component} from {connection_source(connection)}"
    )
    path = export_component(
        connection=connection,
        context=context,
        app=app,
        component=component,
        output_path=cast(str | None, args.output),
        progress=print,
    )
    return component_export_summary(
        path, context.project.root if context.project else None
    )


@locked_command
def app_export_command(args: argparse.Namespace) -> str:
    """Exports all components in one OpenROAD application."""

    context = load_context(Path.cwd())
    connection = resolve_openroad_connection(args, context)
    from .sync_guard import binding_status

    if context.project is not None:
        binding_status(connection, context.project.root)
    app = cast(str, args.app)
    root = export_root(context, cast(str | None, args.output))
    print(f"Exporting application {app} from {connection_source(connection)}")
    exported = export_application(
        connection=connection,
        context=context,
        app=app,
        output_path=cast(str | None, args.output),
        progress=print,
    )

    return application_export_summary(root, exported)


def component_export_summary(path: Path, root: Path | None) -> str:
    lines = [f"Wrote {display_path(path, root)}"]
    wml_path = path.with_suffix(".wml")
    if wml_path.is_file():
        lines.append(f"Wrote {display_path(wml_path, root)}")
    lines.append("Export complete")
    return "\n".join(lines)


def application_export_summary(root: Path, exported: ApplicationExport) -> str:
    paths = application_export_paths(root, exported.application.name)
    w4gl_count = len(exported.components)
    wml_count = sum(
        1 for component in exported.components if component.markup is not None
    )
    lines = [
        f"Wrote {display_path(root / exported.application.name / 'app.json', root)}",
        f"Wrote {display_path(paths.xml_path, root)}",
        f"Wrote {w4gl_count} .w4gl {file_label(w4gl_count)}",
    ]
    if wml_count:
        lines.append(f"Wrote {wml_count} .wml {file_label(wml_count)}")
    component_label = "component" if w4gl_count == 1 else "components"
    lines.append(f"Export complete: {w4gl_count} {component_label}")
    return "\n".join(lines)


def file_label(count: int) -> str:
    return "file" if count == 1 else "files"


def display_path(path: Path, root: Path | None) -> str:
    if root is None:
        return str(path)
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


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


def run_command(args: argparse.Namespace) -> int:
    context = load_context(Path.cwd())
    connection = resolve_openroad_connection(args, context)
    root = context.project.root if context.project else Path.cwd()
    testing = args.command == "test"
    if args.app:
        suites = [TestApplication(args.app)]
    elif context.project:
        suites = test_applications(root)
    else:
        raise ProjectError("Test requires a project tests configuration or --app")
    exit_code = 0
    for configured in suites:
        suite = TestApplication(
            configured.application,
            args.component or configured.component,
            args.timeout if args.timeout is not None else configured.timeout_seconds,
        )
        artifacts = root / ".openroad" / "runs" / uuid4().hex
        print(
            f"Running {suite.application} ({suite.timeout_seconds}s timeout)",
            flush=True,
        )
        try:
            result = execute_application(
                connection, suite, context.env, artifacts, testing
            )
        except (OSError, subprocess.SubprocessError) as ex:
            raise ProjectError(
                f"Application runner failed ({type(ex).__name__}); artifacts: {artifacts}"
            ) from ex
        if args.trace or not testing:
            print(result.trace)
            if result.output:
                print(result.output)
        print(f"Artifacts: {artifacts}")
        if result.timed_out:
            print("ERROR: Application timed out", file=sys.stderr)
            exit_code = 1
        process_failed = result.exit_code != 0
        if testing:
            try:
                summary = report_summary(result.report)
                print(
                    f"Tests: {summary.tests}, failures: {summary.failures}, errors: {summary.errors}, skipped: {summary.skipped}"
                )
                for message in summary.messages:
                    print(message)
                if summary.failures or summary.errors:
                    exit_code = 1
                elif result.exit_code == 2 and summary.skipped > 0:
                    # Actian's framework reserves 2 for suites with skipped tests.
                    process_failed = False
            except ProjectError as ex:
                print(str(ex), file=sys.stderr)
                if not args.trace:
                    print(result.trace[-4000:], file=sys.stderr)
                exit_code = 1
        if result.exit_code:
            suffix = " (framework reports skipped tests)" if not process_failed else ""
            print(f"OpenROAD process exit code: {result.exit_code}{suffix}")
        if process_failed:
            exit_code = 1
    return exit_code


@locked_command
def component_import_command(args: argparse.Namespace) -> str:
    context = load_context(Path.cwd())
    if context.project is None:
        raise ProjectError("Import requires a gorak project")
    connection = resolve_openroad_connection(args, context)
    from .sync_guard import binding_status

    if context.project is not None:
        binding_status(connection, context.project.root)
    operation = import_component(
        connection,
        context.project.root,
        args.app,
        args.component,
        args.dry_run,
    )
    outcome = (
        "Import preview prepared" if args.dry_run else "Import compiled and verified"
    )
    return f"{outcome}. Artifacts: {operation}"


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


@locked_command
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


@locked_command
def sync_command(args: argparse.Namespace) -> str:
    """Export locally tracked components that changed in OpenROAD."""

    context = load_context(Path.cwd())
    connection = resolve_openroad_connection(args, context)
    from .sync_guard import guard_sync

    if context.project is not None:
        if getattr(args, "bind", False) and (
            getattr(args, "push", False) or getattr(args, "dry_run", False)
        ):
            raise ProjectError(
                "Use --bind on its own; it verifies the baseline without syncing"
            )
        if getattr(args, "push", False) or getattr(args, "bind", False):
            plan = guard_sync(
                connection,
                context.project.root,
                push=getattr(args, "push", False),
                bind=getattr(args, "bind", False),
                dry_run=getattr(args, "dry_run", False),
            )
            if (
                getattr(args, "push", False)
                and plan
                and all(change.action == "unchanged" for change in plan)
            ):
                label = (
                    "Push dry run"
                    if getattr(args, "dry_run", False)
                    else "Push complete"
                )
                return f"{label}: no changes (verified comparison)"
        if getattr(args, "bind", False):
            return "Sync baseline verified and bound to the configured target"
    if getattr(args, "push", False):
        from .push import push_project

        if context.project is None:
            raise ProjectError("Push requires a gorak project")
        return push_project(connection, context.project.root, args.dry_run)
    if getattr(args, "dry_run", False):
        raise ProjectError("--dry-run requires --push")
    print(f"Syncing from {connection_source(connection)}")
    result = sync_project(connection, context, progress=print)
    component_label = "component" if result.exported == 1 else "components"
    return (
        f"Sync complete: checked {result.checked}, "
        f"changed {result.changed}, exported {result.exported} {component_label}"
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
    from .remote import ssh_session

    with ssh_session():
        dispatch(argv)


def dispatch(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)

    parser = build_parser()
    parsed = parser.parse_args(args)

    try:
        if parsed.command == "install":
            from .installation import export_installation_sql, installation_sql

            if parsed.check and parsed.upgrade:
                raise ProjectError("--check cannot be combined with --upgrade")
            if parsed.check:
                from .connection import require_odbc_settings
                from .installation_check import check_installation

                connection = resolve_openroad_connection(
                    parsed, load_context(Path.cwd())
                )
                report = check_installation(require_odbc_settings(connection))
                print(json.dumps(report.as_dict(), indent=2))
                raise SystemExit(1 if report.issues else 0)
            if parsed.export_sql is None:
                from .install_backend import install_tracking

                context = load_context(Path.cwd())
                if context.project is None:
                    raise ProjectError("Direct installation requires a gorak project")
                connection = resolve_openroad_connection(parsed, context)
                report = install_tracking(
                    connection,
                    context.project.root / ".openroad" / "installations",
                    upgrade=parsed.upgrade,
                )
                print(json.dumps(report.as_dict(), indent=2))
                return
            if parsed.export_sql == "-":
                print(installation_sql(upgrade=parsed.upgrade), end="")
            else:
                export_installation_sql(Path(parsed.export_sql), upgrade=parsed.upgrade)
                print(
                    f"Exported capture-only installation SQL to {parsed.export_sql}; no database changes made"
                )
            return
        if parsed.command == "journal":
            from .connection import require_odbc_settings
            from .journal import acknowledgment_store, poll_journal
            from .project_lock import project_lock

            context = load_context(Path.cwd())
            if context.project is None:
                raise ProjectError("Journal inspection requires a gorak project")
            connection = resolve_openroad_connection(parsed, context)
            root = context.project.root
            if (
                sum(
                    (
                        parsed.reconcile,
                        parsed.map,
                        parsed.verify_selective,
                        parsed.rebootstrap,
                    )
                )
                > 1
            ):
                raise ProjectError(
                    "Choose one journal mode: --map, --reconcile, --verify-selective, or --rebootstrap"
                )
            if parsed.verify_selective or parsed.rebootstrap:
                from .journal_snapshot import verify_selective_snapshot

                print(
                    json.dumps(
                        verify_selective_snapshot(
                            connection, root, parsed.limit, rebootstrap=True
                        )
                        if parsed.rebootstrap
                        else verify_selective_snapshot(connection, root, parsed.limit),
                        indent=2,
                    )
                )
                return
            if parsed.reconcile:
                from .journal_reconcile import reconcile_journal

                print(
                    json.dumps(
                        reconcile_journal(connection, root, parsed.limit), indent=2
                    )
                )
                return
            with project_lock(root, "journal"):
                with acknowledgment_store(
                    root / ".openroad" / "journal.sqlite3"
                ) as store:
                    batch = poll_journal(
                        require_odbc_settings(connection), store, parsed.limit
                    )
            mapping = None
            if parsed.map:
                from .journal_mapping import map_applications

                mapping = map_applications(
                    require_odbc_settings(connection), batch
                ).as_dict()
            print(
                json.dumps(
                    {
                        **({"mapping": mapping} if mapping is not None else {}),
                        "installation_id": batch.installation_id,
                        "events": [event.as_dict() for event in batch.events],
                        "scanned_events": batch.scanned_events,
                        "acknowledged": False,
                        "incremental_ready": False,
                    },
                    indent=2,
                )
            )
            return
        if parsed.command == "recover":
            from .recovery import recover_push

            context = load_context(Path.cwd())
            if context.project is None:
                raise ProjectError("Recovery requires a gorak project")
            print(
                recover_push(
                    resolve_openroad_connection(parsed, context), context.project.root
                )
            )
            return
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

        if parsed.command == "remote" and parsed.remote_command == "check":
            print(remote_check_command(parsed))
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

        if parsed.command == "status":
            from .sync_guard import binding_status
            from .sync_plan import format_plan, plan_project

            context = load_context(Path.cwd())
            if context.project is None:
                raise ProjectError("Status requires a gorak project")
            connection = resolve_openroad_connection(parsed, context)
            print(
                json.dumps(
                    {
                        "baseline_target": binding_status(
                            connection, context.project.root
                        ),
                        "changes": format_plan(
                            plan_project(connection, context.project.root)
                        ),
                    },
                    indent=2,
                )
            )
            return
        if parsed.command == "sync":
            print(sync_command(parsed))
            return

        if parsed.command == "component" and parsed.component_command == "import":
            print(component_import_command(parsed))
            return

        if parsed.command == "debug" and parsed.debug_command == "audit":
            print(debug_audit_command(parsed))
            return
        if parsed.command in {"run", "test"}:
            raise SystemExit(run_command(parsed))
    except ProjectError as ex:
        print(format_cli_error(ex), file=sys.stderr)
        raise SystemExit(1) from ex
    except (LocalCommandError, RemoteCommandError, SQLAlchemyError, pyodbc.Error) as ex:
        print(format_cli_error(ex), file=sys.stderr)
        raise SystemExit(1) from ex
    except FileNotFoundError as ex:
        print(format_cli_error(ex), file=sys.stderr)
        raise SystemExit(1) from ex

    parser.print_help()
    raise SystemExit(1)


def format_cli_error(error: BaseException) -> str:
    if isinstance(error, ProjectError):
        return f"ERROR: {error}"
    if isinstance(error, LocalCommandError):
        return format_backend_error("Local backend error", error)
    if isinstance(error, RemoteCommandError):
        return format_backend_error("Remote backend error", error)
    if isinstance(error, (SQLAlchemyError, pyodbc.Error)):
        return format_backend_error("ODBC backend error", error)
    if isinstance(error, FileNotFoundError):
        command = error.filename or str(error)
        return f"ERROR: Command not found: {command}"

    return f"ERROR: {error}"


def format_backend_error(title: str, error: BaseException) -> str:
    message = concise_error_text(str(error))
    if not message:
        return f"ERROR: {title}"
    return f"ERROR: {title}\n{message}"


def concise_error_text(message: str) -> str:
    lines = [
        line.strip()
        for line in message.splitlines()
        if line.strip() and not line.strip().startswith("** WARNING:")
    ]
    return "\n".join(lines[:4])


if __name__ == "__main__":
    main()

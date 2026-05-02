import argparse
import csv
import io
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

from lxml import etree

from .parser import encode_w4gl, parse_xml
from .project import configure_remote, create_project, load_project
from .remote import (
    RemoteApplication,
    RemoteHost,
    backup_component,
    download_file,
    get_app_list,
)


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

    remote_parser = subparsers.add_parser("remote")
    remote_subparsers = remote_parser.add_subparsers(dest="remote_command")

    export_component = remote_subparsers.add_parser("export-component")
    export_component.add_argument("--ssh-target", required=True)
    export_component.add_argument("--gorak-root", required=True)
    export_component.add_argument("--vnode", required=True)
    export_component.add_argument("--database", required=True)
    export_component.add_argument("--app", required=True)
    export_component.add_argument("--component", required=True)
    export_component.add_argument("--output", required=True)

    get_app_list_parser = remote_subparsers.add_parser("get-app-list")
    get_app_list_parser.add_argument("--ssh-target", required=True)
    get_app_list_parser.add_argument("--gorak-root", required=True)
    get_app_list_parser.add_argument("--vnode", required=True)
    get_app_list_parser.add_argument("--database", required=True)
    get_app_list_parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
    )

    return parser


def new_command(args: argparse.Namespace) -> str:
    """Creates a new gorak project."""

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


def export_remote_component(args: argparse.Namespace) -> str:
    """Exports a remote OpenROAD component XML file and downloads it locally."""

    remote = RemoteHost(
        ssh_target=args.ssh_target,
        gorak_root=args.gorak_root,
    )
    remote_xml_path = backup_component(
        remote=remote,
        vnode=args.vnode,
        database=args.database,
        app=args.app,
        component=args.component,
    )
    return download_file(
        remote=remote,
        remote_path=remote_xml_path,
        local_path=args.output,
    )


def remote_applications_to_json(applications: list[RemoteApplication]) -> str:
    """Format remote applications as JSON."""

    return json.dumps([asdict(app) for app in applications], indent=2)


def remote_applications_to_csv(applications: list[RemoteApplication]) -> str:
    """Format remote applications as CSV."""

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["name", "start_component", "description"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(asdict(app) for app in applications)

    return output.getvalue().rstrip("\n")


def get_remote_app_list(args: argparse.Namespace) -> str:
    """Reads remote OpenROAD applications and formats them for stdout."""

    remote = RemoteHost(
        ssh_target=args.ssh_target,
        gorak_root=args.gorak_root,
    )
    applications = get_app_list(
        remote=remote,
        vnode=args.vnode,
        database=args.database,
    )

    if cast(str, args.format) == "csv":
        return remote_applications_to_csv(applications)

    return remote_applications_to_json(applications)


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)

    parser = build_parser()
    parsed = parser.parse_args(args)

    if parsed.command == "new":
        print(new_command(parsed))
        return

    if parsed.command == "config" and parsed.config_command == "remote":
        print(config_remote_command(parsed))
        return

    if parsed.command == "encode":
        print(encode_command(parsed))
        return

    if parsed.command == "remote" and parsed.remote_command == "export-component":
        print(export_remote_component(parsed))
        return

    if parsed.command == "remote" and parsed.remote_command == "get-app-list":
        print(get_remote_app_list(parsed))
        return

    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()

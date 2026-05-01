import argparse
import sys
from collections.abc import Sequence
from typing import cast

from lxml import etree

from .parser import encode_4gl, parse_xml
from .remote import RemoteHost, backup_component, download_file


def encode_xml_file(xml_path: str) -> str:
    """Parses an OpenROAD XML export and returns encoded .4gl text."""

    xml = etree.parse(xml_path)
    component = parse_xml(xml)
    return encode_4gl(component)


def build_parser() -> argparse.ArgumentParser:
    """Builds the gorak CLI argument parser."""

    parser = argparse.ArgumentParser(prog="gorak")
    subparsers = parser.add_subparsers(dest="command")

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

    return parser


def encode_command(args: argparse.Namespace) -> str:
    """Encodes an OpenROAD XML export to .4gl text."""

    xml_file = cast(str, args.xml_file)
    output_path = cast(str | None, args.output)
    output = encode_xml_file(xml_file)
    if output_path is None:
        return output

    with open(output_path, "w") as file:
        file.write(output)
    return output_path


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


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)

    parser = build_parser()
    parsed = parser.parse_args(args)

    if parsed.command == "encode":
        print(encode_command(parsed))
        return

    if parsed.command == "remote" and parsed.remote_command == "export-component":
        print(export_remote_component(parsed))
        return

    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()

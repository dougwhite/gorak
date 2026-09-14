"""CLI entry point for experimental native source archive transport."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .connection import require_odbc_settings, resolve_openroad_connection
from .encoded_graph import UnsupportedSource
from .project import ProjectError, load_context
from .project_lock import locked_command
from .storage_capture import capture
from .storage_directory import read_directory, write_directory
from .storage_restore import restore


@locked_command
def source_command(args: argparse.Namespace) -> str:
    directory = Path(args.directory).absolute()
    try:
        if args.operation != "restore" and args.dry_run:
            raise ProjectError("--dry-run is supported only by source restore")
        if args.operation != "export" and args.app:
            raise ProjectError("--app is supported only by source export")
        if args.operation == "verify":
            archive = read_directory(directory)
            return json.dumps(
                {
                    "archive_valid": True,
                    "applications": len(archive.tables["ii_applications"]),
                    "components": len(archive.tables["ii_components"]),
                },
                indent=2,
            )
        context = load_context(Path.cwd())
        connection = resolve_openroad_connection(args, context)
        settings = require_odbc_settings(connection)
        if connection.database.casefold() != settings.database.casefold():
            raise ProjectError("OpenROAD and ODBC source databases must match")
        if args.operation == "export":
            applications = args.app
            if not applications and context.project is not None:
                applications = sorted(
                    path.parent.name for path in context.project.root.glob("*/app.json")
                )
            if not applications:
                raise ProjectError(
                    "Source export requires --app or a project with application folders"
                )
            if directory.exists():
                raise ProjectError("Source export requires a new output directory")
            archive, stale = capture(settings, applications)
            write_directory(archive, directory)
            return json.dumps(
                {
                    "exported": True,
                    "applications": len(archive.tables["ii_applications"]),
                    "components": len(archive.tables["ii_components"]),
                    "symbolic_stale_dependencies": stale,
                },
                indent=2,
            )
        archive = read_directory(directory)
        result = restore(settings, archive, dry_run=args.dry_run)
        return json.dumps(
            {
                **asdict(result),
                "restored": not args.dry_run,
                "compilation_required": not args.dry_run,
            },
            indent=2,
        )
    except UnsupportedSource as exc:
        raise ProjectError(f"Native source archive operation refused: {exc}") from exc

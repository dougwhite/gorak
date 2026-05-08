"""Local OpenROAD and Ingres command wrappers."""

import subprocess
import tempfile
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

from .domain import Application, ComponentInfo, IncludedApplication
from .sql_output import (
    parse_app_list_output,
    parse_component_list_output,
    parse_include_list_output,
)

REMOTE_SCRIPT_PACKAGE = "gorak.remote_scripts"
RunCommand = Callable[[list[str], str | None], str]


class LocalCommandError(RuntimeError):
    """Raised when a local OpenROAD command fails."""


def build_database_target(vnode: str, database: str) -> str:
    return f"{vnode}::{database}"


def command_path(path: Path) -> str:
    if path.is_absolute():
        return str(path)
    return path.as_posix()


def build_backup_component_command(
    vnode: str,
    database: str,
    app: str,
    component: str,
    output_path: Path,
    log_path: Path,
) -> list[str]:
    return [
        "w4gldev",
        "backupapp",
        "out",
        build_database_target(vnode, database),
        app,
        command_path(output_path),
        "-nowindows",
        f"-c{component}",
        "-xml",
        "-TALL,logonly",
        f"-L{command_path(log_path)}",
    ]


def build_backup_application_command(
    vnode: str,
    database: str,
    app: str,
    output_path: Path,
    log_path: Path,
) -> list[str]:
    return [
        "w4gldev",
        "backupapp",
        "out",
        build_database_target(vnode, database),
        app,
        command_path(output_path),
        "-nowindows",
        "-xml",
        "-TALL,logonly",
        f"-L{command_path(log_path)}",
    ]


def build_sql_command(vnode: str, database: str) -> list[str]:
    return ["sql", build_database_target(vnode, database)]


def run_subprocess(command: list[str], input_text: str | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            input=input_text,
        )
    except subprocess.CalledProcessError as ex:
        output = "\n".join(text.strip() for text in [ex.stdout, ex.stderr] if text)
        raise LocalCommandError(
            f"Local command failed with exit code {ex.returncode}\n{output}"
        ) from ex

    return result.stdout


def backup_component(
    vnode: str,
    database: str,
    app: str,
    component: str,
    output_path: Path,
    run_cmd: RunCommand = run_subprocess,
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        log_path = Path(temp_dir) / f"gorak-export-{component}.log"
        run_cmd(
            build_backup_component_command(
                vnode=vnode,
                database=database,
                app=app,
                component=component,
                output_path=output_path,
                log_path=log_path,
            ),
            None,
        )

    if not output_path.is_file():
        raise LocalCommandError(f"Export did not create expected file: {output_path}")

    return str(output_path)


def backup_application(
    vnode: str,
    database: str,
    app: str,
    output_path: Path,
    run_cmd: RunCommand = run_subprocess,
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        log_path = Path(temp_dir) / f"gorak-export-{app}.log"
        run_cmd(
            build_backup_application_command(
                vnode=vnode,
                database=database,
                app=app,
                output_path=output_path,
                log_path=log_path,
            ),
            None,
        )

    if not output_path.is_file():
        raise LocalCommandError(f"Export did not create expected file: {output_path}")

    return str(output_path)


def get_app_list(
    vnode: str,
    database: str,
    run_cmd: RunCommand = run_subprocess,
) -> list[Application]:
    query = files(REMOTE_SCRIPT_PACKAGE).joinpath("applist.sql").read_text()
    output = run_cmd(build_sql_command(vnode, database), query)
    return parse_app_list_output(output)


def get_component_list(
    vnode: str,
    database: str,
    app: str,
    run_cmd: RunCommand = run_subprocess,
) -> list[ComponentInfo]:
    output = run_cmd(build_sql_command(vnode, database), component_list_query(app))
    return parse_component_list_output(output)


def get_include_list(
    vnode: str,
    database: str,
    app: str,
    run_cmd: RunCommand = run_subprocess,
) -> list[IncludedApplication]:
    output = run_cmd(build_sql_command(vnode, database), include_list_query(app))
    return parse_include_list_output(output)


def component_list_query(app: str) -> str:
    app_name = app.replace("'", "''")
    return "\n".join(
        [
            "select ea.entity_name as application_name, e.entity_name as component_name, e.entity_type, e.short_remark",
            "from ii_entities e",
            "left join ii_entities ea on e.folder_id = ea.entity_id",
            "left join ii_applications a on ea.base_entity_id = a.entity_id",
            "where e.base_entity_id = 0",
            "and e.folder_id != 0",
            f"and lower(ea.entity_name) = lower('{app_name}')",
            r"\p\g",
            "",
        ]
    )


def include_list_query(app: str) -> str:
    app_name = app.replace("'", "''")
    return "\n".join(
        [
            "select e.entity_name as application_name, i.incl_name, i.incl_filename, i.incl_sequence",
            "from ii_incl_apps i",
            "left join ii_entities e on i.app_id = e.entity_id",
            "where i.incl_name != 'core'",
            f"and lower(e.entity_name) = lower('{app_name}')",
            "order by i.incl_sequence",
            r"\p\g",
            "",
        ]
    )

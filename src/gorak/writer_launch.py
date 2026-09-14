"""Configure local and remote OpenROAD launches using the same worker code."""

import re
import sys
from importlib.resources import files
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .errors import ProjectError


def validate_writer(database: str, encoding: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", database) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,32}", encoding
    ):
        raise ProjectError("Invalid revision writer database or encoding")


def local_writer_command(
    command: list[str], database: str | None, encoding: str
) -> list[str]:
    if database is None:
        return command
    validate_writer(database, encoding)
    if command[0] != "w4gldev":
        raise ProjectError("Writer wrapper accepts only OpenROAD commands")
    return [
        sys.executable,
        "-m",
        "gorak.writer_worker",
        "--database",
        database,
        "--encoding",
        encoding,
        "--",
        *command[1:],
    ]


def remote_writer_prefix(database: str | None, encoding: str) -> str:
    if database is None:
        return ""
    validate_writer(database, encoding)
    return f'set "GORAK_WRITER_DATABASE={database}"&& set "GORAK_WRITER_ENCODING={encoding}"&& '


def build_writer_archive(path: Path) -> None:
    """Deterministic zipapp containing the production modules, no copied logic."""
    modules = [
        "errors",
        "writer_worker",
        "writer_artifact",
        "writer_init",
        "writer_settings",
        "revision_installation",
    ]
    content = {
        "__main__.py": "from gorak.writer_worker import main\nraise SystemExit(main())\n",
        "gorak/__init__.py": "",
    }
    content.update(
        {
            f"gorak/{name}.py": files("gorak")
            .joinpath(f"{name}.py")
            .read_text(encoding="utf-8")
            for name in modules
        }
    )
    with ZipFile(path, "x", compression=ZIP_DEFLATED) as archive:
        for name, source in sorted(content.items()):
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, source.encode("utf-8"))

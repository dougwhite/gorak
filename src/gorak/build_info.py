"""Identity of a Python installation or a standalone release artifact."""

import json
import platform
from importlib.metadata import version
from importlib.resources import files


def platform_id() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system not in {"linux", "windows"} or machine not in {"amd64", "x86_64"}:
        raise ValueError("Standalone builds currently support Windows/Linux x64 only")
    return f"{system}-x64"


def build_info() -> dict[str, str]:
    resource = files("gorak").joinpath("binary-build.json")
    if resource.is_file():
        result: dict[str, str] = json.loads(resource.read_text(encoding="utf-8"))
        return result
    return {"version": version("gorak"), "tag": "", "platform": "python"}


def version_text() -> str:
    info = build_info()
    return f"gorak {info['version']} ({info['platform']})"

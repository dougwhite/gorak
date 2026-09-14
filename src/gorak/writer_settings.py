"""Read named startup symbols from the OpenROAD execution host's installation."""

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

from .project import ProjectError

_WINDOWS_ENV = os.name == "nt"


def environment_keys(environment: Mapping[str, str], variable: str) -> list[str]:
    """Match the execution host's environment-name case semantics."""
    return [
        key
        for key in environment
        if (key.upper() == variable if _WINDOWS_ENV else key == variable)
    ]


def installation_startup_value(
    variable: str,
    environment: Mapping[str, str],
    *,
    encoding: str,
) -> str:
    """Read one symbol, never dump the installation environment or search PATH.

    Process-local startup overrides are resolved by writer_environment before this
    fallback. A successful empty result means unset; all lookup failures are errors.
    The caller must execute on the OpenROAD host with the child's environment.
    """
    if not re.fullmatch(r"ING_SET_[A-Z_][A-Z0-9_]{0,31}", variable):
        raise ProjectError("Invalid database startup variable")
    systems = [environment[key] for key in environment_keys(environment, "II_SYSTEM")]
    if len(systems) != 1 or not systems[0] or not Path(systems[0]).is_absolute():
        raise ProjectError("Writer startup lookup requires an absolute II_SYSTEM")
    root = Path(systems[0]) / "ingres"
    filename = "ingprenv.exe" if os.name == "nt" else "ingprenv"
    executable = next(
        (
            path
            for directory in ("bin", "utility")
            if (path := root / directory / filename).is_file()
        ),
        None,
    )
    if executable is None:
        raise ProjectError("Cannot find ingprenv in the selected Ingres installation")
    try:
        completed = subprocess.run(
            [str(executable), variable],
            env=dict(environment),
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Startup SQL may contain sensitive literals. Do not echo captured output
        # or chain TimeoutExpired, whose representation includes subprocess data.
        raise ProjectError("Ingres startup symbol lookup failed") from None
    if (
        completed.returncode != 0
        or completed.stderr
        or len(completed.stdout) > 1024 * 1024
    ):
        raise ProjectError("Ingres startup symbol lookup failed")
    try:
        value = completed.stdout.decode(encoding, errors="strict")
    except (UnicodeError, LookupError):
        raise ProjectError("Cannot decode Ingres startup symbol") from None
    if "\0" in value:
        raise ProjectError("Invalid Ingres startup symbol")
    # ingprenv adds a line ending. Retain SQL whitespace, including any earlier
    # newlines; never strip literals or normalize output before the SQL composer.
    return (
        value.removesuffix("\r\n")
        if value.endswith("\r\n")
        else value.removesuffix("\n")
    )

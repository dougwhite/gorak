"""Dependency-free execution-host wrapper, also packaged as a remote zipapp."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from .errors import ProjectError
from .writer_artifact import writer_environment
from .writer_settings import environment_keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--encoding", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.arguments
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("OpenROAD command required")
    try:
        env = dict(os.environ)
        keys = environment_keys(env, "II_SYSTEM")
        if len(keys) != 1 or not Path(env[keys[0]]).is_absolute():
            raise ProjectError("Writer launch requires an absolute II_SYSTEM")
        executable = (
            Path(env[keys[0]])
            / "ingres/bin"
            / ("w4gldev.exe" if os.name == "nt" else "w4gldev")
        )
        if not executable.is_file():
            raise ProjectError("OpenROAD executable missing from selected installation")
        temporary = env.pop("GORAK_WRITER_TEMP_ROOT", None)
        with writer_environment(
            env,
            args.database,
            encoding=args.encoding,
            temporary_root=Path(temporary) if temporary else None,
        ) as child:
            return subprocess.run(
                [str(executable), *command], env=child, check=False
            ).returncode
    except (ProjectError, OSError):
        # Never echo startup SQL or environment values to shared compile logs.
        print("ERROR: Gorak writer startup or process launch failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Exclusive checkout lock for CLI source mutations."""

import argparse
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from .project import ProjectError, load_context


@contextmanager
def project_lock(
    root: Path, operation: str, *, recover_push: bool = False
) -> Iterator[None]:
    directory = root / ".openroad"
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "mutation.lock"
    try:
        handle = lock.open("x")
    except FileExistsError as ex:
        raise ProjectError(
            f"Another Gorak operation may be active; inspect {lock}. "
            "Remove a stale lock only after confirming its process has stopped."
        ) from ex
    try:
        with handle:
            handle.write(json.dumps({"pid": os.getpid(), "operation": operation}))
            handle.flush()
            for name in ("pull.lock", "pull-pending.json", "push-pending.json"):
                if name == "push-pending.json" and recover_push:
                    continue
                if (directory / name).exists():
                    raise ProjectError(
                        f"Unfinished source operation; inspect {directory / name}"
                    )
            yield
    finally:
        lock.unlink()


def locked_command(
    command: Callable[[argparse.Namespace], str],
) -> Callable[[argparse.Namespace], str]:
    """Hold the lock across planning, remote work, and local installation."""

    @wraps(command)
    def wrapped(args: argparse.Namespace) -> str:
        context = load_context(Path.cwd())
        if context.project is None:
            return command(args)
        with project_lock(context.project.root, command.__name__):
            return command(args)

    return wrapped

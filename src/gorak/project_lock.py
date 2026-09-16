"""Exclusive checkout lock for CLI source mutations."""

import argparse
import json
import os
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import TextIO

import psutil

from .project import ProjectError, load_context


def open_lock(path: Path, operation: str) -> TextIO:
    """Reclaim only a proven-dead local owner; unknown/remote owners remain blocked."""
    try:
        handle = path.open("x")
    except FileExistsError:
        claim = path.with_name(path.name + ".reclaim")
        try:
            reservation = claim.open("x")
        except FileExistsError:
            raise ProjectError(
                f"Lock recovery is already active; inspect {claim}"
            ) from None
        try:
            with reservation:
                before = path.read_bytes()
                try:
                    record = json.loads(before)
                    if record.get("host", socket.gethostname()) != socket.gethostname():
                        raise ValueError
                    pid = record["pid"]
                    if not isinstance(pid, int) or pid <= 0:
                        raise ValueError
                    try:
                        process = psutil.Process(pid)
                        alive = record.get("started") in {None, process.create_time()}
                    except psutil.NoSuchProcess:
                        alive = False
                    if alive or path.read_bytes() != before:
                        raise ValueError
                except (
                    ValueError,
                    KeyError,
                    TypeError,
                    AttributeError,
                    psutil.AccessDenied,
                ):
                    raise ProjectError(
                        f"Another Gorak operation may be active; inspect {path}"
                    ) from None
                path.unlink()
                handle = path.open("x")
        finally:
            claim.unlink()
    handle.write(
        json.dumps(
            {
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "started": psutil.Process().create_time(),
                "operation": operation,
            }
        )
    )
    handle.flush()
    return handle


@contextmanager
def project_lock(
    root: Path,
    operation: str,
    *,
    recover_push: bool = False,
    recover_pull: bool = False,
) -> Iterator[None]:
    directory = root / ".openroad"
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "mutation.lock"
    try:
        handle = open_lock(lock, operation)
    except FileExistsError as ex:
        raise ProjectError(
            f"Another Gorak operation may be active; inspect {lock}. "
            "Remove a stale lock only after confirming its process has stopped."
        ) from ex
    try:
        with handle:
            for name in ("pull.lock", "pull-pending.json", "push-pending.json"):
                if (name == "push-pending.json" and recover_push) or (
                    name == "pull-pending.json" and recover_pull
                ):
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
        with project_lock(
            context.project.root,
            command.__name__,
            recover_push=command.__name__ == "sync_command",
            recover_pull=command.__name__ == "sync_command"
            and getattr(args, "force", False),
        ):
            return command(args)

    return wrapped

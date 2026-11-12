"""Managed standalone installations, with an updater inside each executable.

The new executable runs from staging, so neither Windows file locking nor an old
updater prevents replacing the installed executable. Portable files have no receipt.
"""

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import psutil

from .binary_release import download_binary, latest_release
from .build_info import build_info, version_text
from .errors import ProjectError

RECEIPT = "installation.json"


def executable_name() -> str:
    return "gorak.exe" if os.name == "nt" else "gorak"


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def receipt(root: Path) -> dict[str, Any]:
    try:
        result = json.loads((root / RECEIPT).read_text(encoding="utf-8"))
        if (
            not isinstance(result, dict)
            or result.get("schema") != 1
            or result.get("product") != "gorak"
            or result.get("scope") not in {"user", "system"}
            or result.get("root") != str(root)
        ):
            raise ValueError("invalid installation receipt")
        return result
    except (OSError, ValueError) as error:
        raise ProjectError(
            "Not a managed gorak installation; download portable updates manually"
        ) from error


def managed_root(executable: Path) -> Path:
    path = executable.resolve()
    root = path.parent.parent
    state = receipt(root)
    if path != root / "bin" / executable_name() or state.get("sha256") != file_hash(
        path
    ):
        raise ProjectError("gorak executable does not match its installation receipt")
    return root


def child_environment() -> dict[str, str]:
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def probe(executable: Path, expected: dict[str, str]) -> None:
    result = subprocess.run(
        [str(executable), "--_build-info"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        env=child_environment(),
    )
    try:
        actual = json.loads(result.stdout)
    except ValueError as error:
        raise ProjectError(
            "Downloaded gorak did not report its build identity"
        ) from error
    if actual != expected:
        raise ProjectError("Downloaded gorak has an unexpected build identity")


@contextlib.contextmanager
def install_lock(root: Path) -> Iterator[None]:
    lock = root / ".install-lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ProjectError(
            "Another gorak install/update is active; inspect .install-lock before retrying"
        ) from error
    try:
        yield
    finally:
        lock.rmdir()


def replace_file(source: Path, target: Path) -> None:
    # The Windows one-file bootloader can still hold the old executable briefly
    # after its Python child exits. Bounded retry also tolerates transient scanners.
    deadline = time.monotonic() + 30
    while True:
        try:
            source.replace(target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def install(source: Path, root: Path, scope: str, expected_hash: str) -> None:
    """Replace only a managed executable, retaining the previous working copy."""
    root = root.absolute()
    if scope not in {"user", "system"} or (os.name != "nt" and scope != "user"):
        raise ProjectError("Linux binary installations support user scope only")
    if root.is_symlink() or (root / "bin").is_symlink():
        raise ProjectError("Installation directories must not be symbolic links")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with install_lock(root):
        for path in (
            root / RECEIPT,
            root / "installation.previous.json",
            root / "installation.pending.json",
            root / "update-result.txt",
            root / "bin" / (executable_name() + ".previous"),
            root / "bin" / (executable_name() + ".pending"),
        ):
            if path.is_symlink():
                raise ProjectError(
                    "Managed installation files must not be symbolic links"
                )
        old: dict[str, Any] | None = None
        existing = set(root.iterdir()) - {root / ".install-lock"}
        if existing:
            old = receipt(root)
            if old["scope"] != scope:
                raise ProjectError("Cannot change installation scope during an update")
        target = root / "bin" / executable_name()
        if target.is_symlink():
            raise ProjectError("Installed executable must not be a symbolic link")
        if old is not None and (
            not target.is_file() or file_hash(target) != old.get("sha256")
        ):
            raise ProjectError("Installed executable changed outside the installer")
        if file_hash(source) != expected_hash:
            raise ProjectError("Staged executable checksum changed")
        probe(source, build_info())
        target.parent.mkdir(exist_ok=True)
        pending = target.with_name(target.name + ".pending")
        previous = target.with_name(target.name + ".previous")
        receipt_path = root / RECEIPT
        old_receipt = receipt_path.read_bytes() if old is not None else None
        new_state = {
            "schema": 1,
            "product": "gorak",
            "scope": scope,
            "root": str(root),
            "sha256": expected_hash,
            **build_info(),
        }
        if old_receipt is not None:
            (root / "installation.previous.json").write_bytes(old_receipt)
            shutil.copy2(target, previous)
        replaced = False
        try:
            shutil.copy2(source, pending)
            pending.chmod(0o755)
            if file_hash(pending) != expected_hash:
                raise ProjectError("Staged executable copy failed verification")
            replace_file(pending, target)
            replaced = True
            probe(target, build_info())
            temp_receipt = root / "installation.pending.json"
            temp_receipt.write_text(
                json.dumps(new_state, indent=2) + "\n", encoding="utf-8"
            )
            temp_receipt.replace(receipt_path)
        except BaseException:
            if replaced:
                if old_receipt is not None:
                    shutil.copy2(previous, pending)
                    replace_file(pending, target)
                    receipt_path.write_bytes(old_receipt)
                else:
                    target.unlink(missing_ok=True)
            raise
        finally:
            pending.unlink(missing_ok=True)
            (root / "installation.pending.json").unlink(missing_ok=True)
            if old is None and not receipt_path.exists():
                with contextlib.suppress(OSError):
                    target.parent.rmdir()


def self_update() -> str:
    if not getattr(sys, "frozen", False):
        raise ProjectError(
            "This is a Python/source installation; update it using its package manager or checkout"
        )
    root = managed_root(Path(sys.executable))
    state = receipt(root)
    tag, asset = latest_release(build_info()["platform"])
    if tag == state.get("tag"):
        return f"gorak is already at {tag}"
    staging = Path(tempfile.mkdtemp(prefix="gorak-update-"))
    candidate = staging / executable_name()
    handed_off = False
    try:
        download_binary(tag, asset, candidate)
        expected = {
            "version": asset["version"],
            "platform": build_info()["platform"],
            "tag": tag,
        }
        probe(candidate, expected)
        command = [
            str(candidate),
            "--_install",
            "--root",
            str(root),
            "--scope",
            state["scope"],
            "--sha256",
            asset["sha256"],
        ]
        if os.name == "nt":
            command.extend(["--wait-pid", str(os.getpid())])
            launch_windows_update(command, state["scope"])
            handed_off = True
            return f"Updating to {tag} after gorak exits. Result: {root / 'update-result.txt'}"
        subprocess.run(command, check=True, env=child_environment())
        return f"Updated gorak to {tag}"
    except (OSError, subprocess.SubprocessError) as error:
        raise ProjectError(f"gorak update failed: {error}") from error
    finally:
        if not handed_off:
            shutil.rmtree(staging)


def launch_windows_update(command: list[str], scope: str) -> None:
    if scope == "system":
        if sys.platform != "win32":
            raise ProjectError("System-wide binary updates require Windows")
        # ShellExecute's runas verb supplies the standard UAC consent prompt.
        execute = ctypes.windll.shell32.ShellExecuteW
        execute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
        ]
        execute.restype = ctypes.c_void_p
        result = execute(
            None, "runas", command[0], subprocess.list2cmdline(command[1:]), None, 1
        )
        if result is None or result <= 32:
            raise ProjectError(
                "Administrator approval was cancelled or the updater could not start"
            )
    else:
        subprocess.Popen(
            command,
            env=child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x00000200
            | 0x00000008,  # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
        )


def write_result(root: Path, message: str) -> None:
    """Best-effort diagnostics must not turn a successful install into a failure."""
    with contextlib.suppress(OSError, ProjectError):
        receipt(root)
        path = root / "update-result.txt"
        if not path.is_symlink():
            path.write_text(message + "\n", encoding="utf-8")


def installer_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="gorak standalone installation worker")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--scope", choices=["user", "system"], default="user")
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--wait-pid", type=int)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.wait_pid:
            try:
                psutil.Process(args.wait_pid).wait(timeout=60)
            except psutil.NoSuchProcess:
                pass
        install(Path(sys.executable), args.root, args.scope, args.sha256)
        message = f"Installed {version_text()} in {root}"
        write_result(root, message)
        print(message)
        return 0
    except (ProjectError, OSError, subprocess.SubprocessError, psutil.Error) as error:
        message = f"gorak installation failed: {error}"
        print(message, file=sys.stderr)
        write_result(root, message)
        return 1

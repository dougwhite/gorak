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
from importlib.resources import files
from pathlib import Path
from typing import Any

import psutil

from .binary_release import download_binary, latest_release
from .build_info import build_info, version_text
from .errors import ProjectError

RECEIPT = "installation.json"
TRANSACTION = ".install-transaction.json"
SYSTEM_HELPER = "system-update.ps1"


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
    digest = file_hash(path)
    # An interrupted swap may leave the new executable beside the old receipt.
    # Permit only the exact journaled candidate to launch a staged repair worker.
    interrupted = False
    if (root / TRANSACTION).exists():
        transaction = read_transaction(root)
        interrupted = (
            transaction["old"] == state and transaction["new"]["sha256"] == digest
        )
    if path != root / "bin" / executable_name() or (
        state.get("sha256") != digest and not interrupted
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
    if lock.is_symlink() or lock.is_dir():
        raise ProjectError(
            "Invalid or legacy installation lock; inspect before retrying"
        )
    # Keep the inode: unlinking a lock file permits concurrent locks on two inodes.
    # Kernel locks release on process termination, including abrupt worker death.
    with lock.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ProjectError("Another gorak install/update is active") from error
        try:
            yield
        finally:
            if sys.platform == "win32":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def atomic_write(path: Path, data: bytes) -> None:
    pending = path.with_suffix(".pending.json")
    if pending.is_symlink():
        raise ProjectError("Managed installation files must not be symbolic links")
    try:
        with pending.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def read_transaction(root: Path) -> dict[str, Any]:
    path = root / TRANSACTION
    try:
        if path.is_symlink():
            raise ValueError("symlink")
        transaction = json.loads(path.read_bytes())
        if not isinstance(transaction, dict) or transaction.get("schema") != 1:
            raise ValueError("schema")
        for key in ("new", "old"):
            state = transaction[key]
            if state is None and key == "old":
                continue
            if (
                not isinstance(state, dict)
                or state.get("root") != str(root)
                or state.get("product") != "gorak"
                or state.get("schema") != 1
                or state.get("scope") not in {"user", "system"}
                or not isinstance(state.get("sha256"), str)
            ):
                raise ValueError("receipt")
        return transaction
    except (OSError, ValueError, KeyError) as error:
        raise ProjectError(
            "Invalid interrupted-install journal; installation unchanged"
        ) from error


def recover_install(root: Path) -> None:
    """Complete or roll back a journaled swap. Caller holds the installation lock."""
    if not (root / TRANSACTION).exists():
        return
    transaction = read_transaction(root)
    old, new = transaction["old"], transaction["new"]
    target = root / "bin" / executable_name()
    previous = target.with_name(target.name + ".previous")
    helper = root / SYSTEM_HELPER
    for path in (
        target,
        previous,
        root / "installation.previous.json",
        helper,
        root / (SYSTEM_HELPER + ".previous"),
        root / RECEIPT,
    ):
        if path.is_symlink():
            raise ProjectError("Recovery files must not be symbolic links")
    current_hash = file_hash(target) if target.exists() else None
    allowed = {new["sha256"], old["sha256"] if old else None, None}
    if current_hash not in allowed:
        raise ProjectError("Interrupted installation was modified; refusing recovery")
    try:
        committed = receipt(root) == new and current_hash == new["sha256"]
        if new.get("helper_sha256"):
            committed = (
                committed
                and helper.is_file()
                and file_hash(helper) == new["helper_sha256"]
            )
    except ProjectError:
        committed = False
    if not committed:
        if old is not None:
            saved = (root / "installation.previous.json").read_bytes()
            if json.loads(saved) != old or file_hash(previous) != old["sha256"]:
                raise ProjectError("Previous installation failed recovery verification")
            if old.get("helper_sha256"):
                saved_helper = root / (SYSTEM_HELPER + ".previous")
                if file_hash(saved_helper) != old["helper_sha256"]:
                    raise ProjectError("Previous updater failed recovery verification")
                restore_copy(saved_helper, helper)
            else:
                helper.unlink(missing_ok=True)
            if current_hash != old["sha256"]:
                restore_copy(previous, target)
            if not (root / RECEIPT).exists() or (root / RECEIPT).read_bytes() != saved:
                atomic_write(root / RECEIPT, saved)
        else:
            target.unlink(missing_ok=True)
            helper.unlink(missing_ok=True)
            target.with_name(target.name + ".pending").unlink(missing_ok=True)
            (root / (SYSTEM_HELPER + ".pending")).unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                target.parent.rmdir()
    (root / "installation.pending.json").unlink(missing_ok=True)
    target.with_name(target.name + ".pending").unlink(missing_ok=True)
    (root / (SYSTEM_HELPER + ".pending")).unlink(missing_ok=True)
    (root / TRANSACTION).unlink()


def restore_copy(source: Path, target: Path) -> None:
    pending = target.with_name(target.name + ".pending")
    if pending.is_symlink():
        raise ProjectError("Managed installation files must not be symbolic links")
    try:
        shutil.copy2(source, pending)
        replace_file(pending, target)
    finally:
        pending.unlink(missing_ok=True)


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
    if scope == "system" and root != system_root():
        raise ProjectError("System installations must use Program Files\\gorak")
    root.mkdir(parents=True, exist_ok=True)
    with install_lock(root):
        for path in (
            root / RECEIPT,
            root / "installation.previous.json",
            root / "installation.pending.json",
            root / "update-result.txt",
            root / TRANSACTION,
            root / SYSTEM_HELPER,
            root / (SYSTEM_HELPER + ".previous"),
            root / (SYSTEM_HELPER + ".pending"),
            root / "bin" / (executable_name() + ".previous"),
            root / "bin" / (executable_name() + ".pending"),
        ):
            if path.is_symlink():
                raise ProjectError(
                    "Managed installation files must not be symbolic links"
                )
        recover_install(root)
        old: dict[str, Any] | None = None
        # Pending files may remain if a process died before committing its journal.
        (root / ".install-transaction.pending.json").unlink(missing_ok=True)
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
        helper_data = (
            files("gorak").joinpath("install_scripts/system-update.ps1").read_bytes()
            if scope == "system"
            else None
        )
        if helper_data is not None:
            new_state["helper_sha256"] = hashlib.sha256(helper_data).hexdigest()
        if old_receipt is not None:
            atomic_write(root / "installation.previous.json", old_receipt)
            shutil.copy2(target, previous)
            if old and old.get("helper_sha256"):
                helper = root / SYSTEM_HELPER
                if file_hash(helper) != old["helper_sha256"]:
                    raise ProjectError(
                        "Installed updater changed outside the installer"
                    )
                shutil.copy2(helper, root / (SYSTEM_HELPER + ".previous"))
        # Persist an immutable before-image before any active file is changed.
        atomic_write(
            root / TRANSACTION,
            json.dumps({"schema": 1, "old": old, "new": new_state}).encode(),
        )
        try:
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(source, pending)
            pending.chmod(0o755)
            if file_hash(pending) != expected_hash:
                raise ProjectError("Staged executable copy failed verification")
            replace_file(pending, target)
            probe(target, build_info())
            if helper_data is not None:
                helper_pending = root / (SYSTEM_HELPER + ".pending")
                helper_pending.write_bytes(helper_data)
                replace_file(helper_pending, root / SYSTEM_HELPER)
            atomic_write(
                receipt_path, (json.dumps(new_state, indent=2) + "\n").encode()
            )
            (root / TRANSACTION).unlink()
        except BaseException:
            recover_install(root)
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
    if state["scope"] == "system":
        launch_system_update(root)
        return f"Updating gorak after administrator approval. Result: {root / 'update-result.txt'}"
    tag, asset = latest_release(build_info()["platform"])
    if tag == state.get("tag") and not (root / TRANSACTION).exists():
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
        raise ProjectError("System updates must use the protected installed helper")
    subprocess.Popen(
        command,
        env=child_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x00000200
        | 0x00000008,  # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    )


def system_root() -> Path:
    if sys.platform != "win32":
        raise ProjectError("System-wide binary updates require Windows")
    buffer = ctypes.create_unicode_buffer(32768)
    # CSIDL_PROGRAM_FILES: do not trust caller-controlled environment variables.
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x26, None, 0, buffer)
    if result != 0:
        raise ProjectError("Cannot locate Program Files")
    return Path(buffer.value) / "gorak"


def launch_system_update(root: Path) -> None:
    if root != system_root() or root.is_symlink():
        raise ProjectError("System updater must be installed in Program Files\\gorak")
    helper = root / SYSTEM_HELPER
    state = receipt(root)
    helper_hashes = {state.get("helper_sha256")}
    if (root / TRANSACTION).exists():
        transaction = read_transaction(root)
        if transaction["old"] == state:
            helper_hashes.add(transaction["new"].get("helper_sha256"))
    if (
        helper.is_symlink()
        or not helper.is_file()
        or file_hash(helper) not in helper_hashes
    ):
        raise ProjectError(
            "Protected system updater is missing or changed; rerun the installer"
        )
    launch_elevated_helper(helper)


def launch_elevated_helper(helper: Path) -> None:
    if sys.platform != "win32":
        raise ProjectError("System-wide binary updates require Windows")
    buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)):
        raise ProjectError("Cannot locate Windows PowerShell")
    powershell = Path(buffer.value) / "WindowsPowerShell/v1.0/powershell.exe"
    command = [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(helper),
        "-WaitPid",
        str(os.getpid()),
    ]
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
        None,
        "runas",
        str(powershell),
        subprocess.list2cmdline(command),
        str(helper.parent),
        1,
    )
    if result is None or result <= 32:
        raise ProjectError(
            "Administrator approval was cancelled or the updater could not start"
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

"""Crash acceptance uses synthetic files in disposable directories, never services."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from gorak import binary_install as installer
from gorak.errors import ProjectError

WORKER = """
import os
import sys
from pathlib import Path
from gorak import binary_install as worker
root, candidate = Path(sys.argv[1]), Path(sys.argv[2])
phase = sys.argv[3]
worker.probe = lambda *a: None
worker.build_info = lambda: {"tag": "v2", "version": "2", "platform": "test"}
atomic = worker.atomic_write
replace = worker.replace_file
path_replace = Path.replace
def replace_path(path, target):
    if phase == "receipt_pending" and path.name == "installation.pending.json":
        os._exit(23)
    return path_replace(path, target)
Path.replace = replace_path
def atomic_write(path, data):
    atomic(path, data)
    if (phase == "journal" and path.name == worker.TRANSACTION) or (
        phase == "receipt" and path.name == worker.RECEIPT
    ):
        os._exit(23)
def replace_file(source, target):
    if phase == "copy_pending" and target.name == worker.executable_name():
        os._exit(23)
    replace(source, target)
    if phase == "swap" and target.name == worker.executable_name():
        os._exit(23)
worker.atomic_write = atomic_write
worker.replace_file = replace_file
worker.install(candidate, root, "user", worker.file_hash(candidate))
raise AssertionError("Crash point was not reached")
"""


@pytest.mark.parametrize("first_install", [False, True])
@pytest.mark.parametrize(
    "phase", ["journal", "copy_pending", "swap", "receipt_pending", "receipt"]
)
def test_process_death_releases_lock_and_next_install_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, first_install: bool
) -> None:
    root = tmp_path / "managed"
    candidate = tmp_path / "candidate"
    candidate.write_bytes(b"synthetic old executable")
    monkeypatch.setattr(installer, "probe", lambda *args: None)
    monkeypatch.setattr(
        installer,
        "build_info",
        lambda: {"tag": "v1", "version": "1", "platform": "test"},
    )
    if not first_install:
        installer.install(candidate, root, "user", installer.file_hash(candidate))
    candidate.write_bytes(b"synthetic new executable")
    worker = tmp_path / "worker.py"
    worker.write_text(WORKER)
    result = subprocess.run(
        [sys.executable, str(worker), str(root), str(candidate), phase],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 23, result.stderr
    assert (root / installer.TRANSACTION).exists()
    with installer.install_lock(root):
        installer.recover_install(root)
    assert not (root / installer.TRANSACTION).exists()
    if phase == "receipt":
        assert installer.receipt(root)["tag"] == "v2"
        assert (
            root / "bin" / installer.executable_name()
        ).read_bytes() == candidate.read_bytes()
    elif not first_install:
        assert installer.receipt(root)["tag"] == "v1"
        assert (
            root / "bin" / installer.executable_name()
        ).read_bytes() == b"synthetic old executable"
    else:
        assert not (root / installer.RECEIPT).exists()
        assert not (root / "bin").exists()
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    assert installer.managed_root(root / "bin" / installer.executable_name()) == root


def test_recovery_refuses_damaged_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "managed"
    candidate = tmp_path / "candidate"
    candidate.write_bytes(b"old")
    monkeypatch.setattr(installer, "probe", lambda *args: None)
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    old = installer.receipt(root)
    executable = root / "bin" / installer.executable_name()
    executable.write_bytes(b"new")
    new = {**old, "sha256": installer.file_hash(executable)}
    (root / installer.TRANSACTION).write_text(
        json.dumps({"schema": 1, "old": old, "new": new})
    )
    (root / "installation.previous.json").write_text(json.dumps(old))
    executable.with_name(executable.name + ".previous").write_bytes(b"damaged")
    with (
        installer.install_lock(root),
        pytest.raises(ProjectError, match="recovery verification"),
    ):
        installer.recover_install(root)
    assert executable.read_bytes() == b"new"
    assert (root / installer.TRANSACTION).exists()

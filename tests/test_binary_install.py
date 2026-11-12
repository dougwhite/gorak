import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from gorak import binary_install as installer
from gorak.errors import ProjectError


@pytest.fixture
def candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "candidate"
    source.write_bytes(b"new gorak")
    monkeypatch.setattr(installer, "probe", lambda *a: None)
    monkeypatch.setattr(
        installer,
        "build_info",
        lambda: {"tag": "v1", "version": "1", "platform": "linux-x64"},
    )
    return source


def target(root: Path) -> Path:
    return root / "bin" / installer.executable_name()


def test_install_and_replace_retains_previous(candidate: Path, tmp_path: Path) -> None:
    root = tmp_path / "installation with spaces"
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    assert installer.managed_root(target(root)) == root
    old_receipt = (root / installer.RECEIPT).read_bytes()
    candidate.write_bytes(b"replacement gorak")
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    assert target(root).read_bytes() == b"replacement gorak"
    assert (
        target(root).with_name(target(root).name + ".previous").read_bytes()
        == b"new gorak"
    )
    assert (root / "installation.previous.json").read_bytes() == old_receipt
    assert installer.managed_root(target(root)) == root


@pytest.mark.parametrize(
    "scope",
    [
        "user",
        pytest.param(
            "system",
            marks=pytest.mark.skipif(
                sys.platform != "win32", reason="Windows system installation"
            ),
        ),
    ],
)
@pytest.mark.parametrize("committed_journal", [False, True])
def test_repeat_install_preserves_last_distinct_build(
    candidate: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    committed_journal: bool,
) -> None:
    root = tmp_path / "managed"
    monkeypatch.setattr(installer, "system_root", lambda: root)
    resources = tmp_path / "resources"
    (resources / "install_scripts").mkdir(parents=True)
    resource = resources / "install_scripts" / installer.SYSTEM_HELPER
    resource.write_bytes(b"helper v1")
    monkeypatch.setattr(installer, "files", lambda package: resources)
    installer.install(candidate, root, scope, installer.file_hash(candidate))
    old = installer.receipt(root)
    candidate.write_bytes(b"executable v2")
    resource.write_bytes(b"helper v2")
    monkeypatch.setattr(
        installer,
        "build_info",
        lambda: {"tag": "v2", "version": "2", "platform": "test"},
    )
    installer.install(candidate, root, scope, installer.file_hash(candidate))
    new = installer.receipt(root)
    if committed_journal:
        (root / installer.TRANSACTION).write_text(
            json.dumps({"schema": 1, "old": old, "new": new})
        )
    paths = [
        target(root),
        target(root).with_name(target(root).name + ".previous"),
        root / installer.RECEIPT,
        root / "installation.previous.json",
    ]
    if scope == "system":
        paths.extend(
            [
                root / installer.SYSTEM_HELPER,
                root / (installer.SYSTEM_HELPER + ".previous"),
            ]
        )
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

    def unexpected_write(*args: Any) -> None:
        raise AssertionError(
            "An identical install must not write a journal or rotate backups"
        )

    monkeypatch.setattr(installer, "atomic_write", unexpected_write)
    installer.install(candidate, root, scope, installer.file_hash(candidate))
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
    } == before
    assert not (root / installer.TRANSACTION).exists()
    assert json.loads((root / "installation.previous.json").read_bytes()) == old
    assert installer.file_hash(paths[1]) == old["sha256"]
    if scope == "system":
        (root / installer.SYSTEM_HELPER).write_bytes(b"tampered")
        with pytest.raises(ProjectError, match="updater changed"):
            installer.install(candidate, root, scope, installer.file_hash(candidate))
        assert (
            root / (installer.SYSTEM_HELPER + ".previous")
        ).read_bytes() == b"helper v1"


def test_failed_post_install_probe_restores_executable_and_receipt(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "managed"
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    before = (root / installer.RECEIPT).read_bytes()
    candidate.write_bytes(b"broken new executable")

    def probe(path: Path, expected: dict[str, str]) -> None:
        if path == target(root):
            raise ProjectError("startup failed")

    monkeypatch.setattr(installer, "probe", probe)
    with pytest.raises(ProjectError, match="startup failed"):
        installer.install(candidate, root, "user", installer.file_hash(candidate))
    assert target(root).read_bytes() == b"new gorak"
    assert (root / installer.RECEIPT).read_bytes() == before
    with installer.install_lock(root):
        pass


def test_bad_candidate_preserves_installed_version(
    candidate: Path, tmp_path: Path
) -> None:
    root = tmp_path / "managed"
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    with pytest.raises(ProjectError, match="checksum"):
        installer.install(candidate, root, "user", "0" * 64)
    assert installer.managed_root(target(root)) == root


def test_installer_refuses_unmanaged_directory(candidate: Path, tmp_path: Path) -> None:
    root = tmp_path / "other"
    root.mkdir()
    (root / "user-file").write_text("keep me")
    with pytest.raises(ProjectError, match="Not a managed"):
        installer.install(candidate, root, "user", installer.file_hash(candidate))
    assert (root / "user-file").read_text() == "keep me"


def test_changed_executable_and_concurrent_update_are_refused(
    candidate: Path, tmp_path: Path
) -> None:
    root = tmp_path / "managed"
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    with installer.install_lock(root), pytest.raises(ProjectError, match="Another"):
        installer.install(candidate, root, "user", installer.file_hash(candidate))
    target(root).write_bytes(b"manually changed")
    with pytest.raises(ProjectError, match="outside the installer"):
        installer.install(candidate, root, "user", installer.file_hash(candidate))
    with pytest.raises(ProjectError, match="does not match"):
        installer.managed_root(target(root))


def test_portable_cannot_self_update(tmp_path: Path) -> None:
    portable = tmp_path / "portable"
    portable.write_bytes(b"executable")
    with pytest.raises(ProjectError, match="manually"):
        installer.managed_root(portable)


def test_copied_install_receipt_does_not_authorize_a_different_location(
    candidate: Path, tmp_path: Path
) -> None:
    root = tmp_path / "managed"
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    copied = tmp_path / "copied"
    copied.mkdir()
    (copied / installer.RECEIPT).write_bytes((root / installer.RECEIPT).read_bytes())
    with pytest.raises(ProjectError, match="Not a managed"):
        installer.receipt(copied)


def test_updater_downloads_before_handoff_and_keeps_scope(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "managed"
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(target(root)))
    monkeypatch.setattr(
        installer,
        "latest_release",
        lambda target: (
            "v2",
            {"name": "gorak-linux-x64", "sha256": "a" * 64, "version": "2"},
        ),
    )
    downloads: list[Path] = []

    def download(tag: str, asset: dict[str, str], path: Path) -> None:
        downloads.append(path)
        path.write_bytes(b"next gorak")

    monkeypatch.setattr(installer, "download_binary", download)
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert Path(command[0]).read_bytes() == b"next gorak"
        assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(
        installer,
        "launch_windows_update",
        lambda command, scope: commands.append(command),
    )
    assert "v2" in installer.self_update()
    assert commands[0][1:7] == [
        "--_install",
        "--root",
        str(root),
        "--scope",
        "user",
        "--sha256",
    ]
    # Linux cleans staging synchronously. Windows retains it while its worker runs.
    if os.name != "nt":
        assert not downloads[0].parent.exists()


def test_current_release_does_not_download(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "managed"
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(target(root)))
    monkeypatch.setattr(installer, "latest_release", lambda target: ("v1", {}))
    assert installer.self_update() == "gorak is already at v1"


def test_receipt_failure_restores_previous_copy(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "managed"
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    old = json.loads((root / installer.RECEIPT).read_text())
    candidate.write_bytes(b"another version")
    original = Path.replace

    def replace(path: Path, destination: Path) -> Path:
        if path.name == "installation.pending.json":
            raise OSError("simulated receipt failure")
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(OSError, match="receipt failure"):
        installer.install(candidate, root, "user", installer.file_hash(candidate))
    assert installer.file_hash(target(root)) == old["sha256"]
    assert installer.receipt(root) == old


def test_build_probe_rejects_wrong_tag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected = {"version": "1", "tag": "v1", "platform": "linux-x64"}
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, json.dumps({**expected, "tag": "v2"})
        ),
    )
    with pytest.raises(ProjectError, match="unexpected build identity"):
        installer.probe(tmp_path / "candidate", expected)


def test_failed_first_install_can_be_retried(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "managed"

    def probe(path: Path, expected: dict[str, str]) -> None:
        if path == target(root):
            raise ProjectError("cannot start")

    monkeypatch.setattr(installer, "probe", probe)
    with pytest.raises(ProjectError, match="cannot start"):
        installer.install(candidate, root, "user", installer.file_hash(candidate))
    assert list(root.iterdir()) == [root / ".install-lock"]
    monkeypatch.setattr(installer, "probe", lambda *a: None)
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    assert installer.managed_root(target(root)) == root


def test_windows_user_handoff_detaches_without_a_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(
        subprocess, "Popen", lambda command, **kwargs: calls.append((command, kwargs))
    )
    command = [
        r"C:\Temp\gorak.exe",
        "--_install",
        "--root",
        r"C:\Users\Example User\gorak",
    ]
    installer.launch_windows_update(command, "user")
    assert calls[0][0] == command
    assert calls[0][1]["creationflags"] == 0x208
    assert calls[0][1]["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "shell" not in calls[0][1]


def test_system_update_does_not_download_or_elevate_a_user_candidate(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected installation"
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    state = installer.receipt(root)
    state["scope"] = "system"
    (root / installer.RECEIPT).write_text(json.dumps(state))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(target(root)))
    calls: list[Path] = []
    monkeypatch.setattr(installer, "launch_system_update", calls.append)

    def unexpected(*args: Any) -> Any:
        raise AssertionError(
            "System download must happen only inside the elevated helper"
        )

    monkeypatch.setattr(installer, "latest_release", unexpected)
    monkeypatch.setattr(installer, "download_binary", unexpected)
    assert "administrator approval" in installer.self_update()
    assert calls == [root]
    with pytest.raises(ProjectError, match="protected installed helper"):
        installer.launch_windows_update([str(candidate)], "system")


def test_system_helper_must_match_protected_installation(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "protected"
    installer.install(candidate, root, "user", installer.file_hash(candidate))
    helper = root / installer.SYSTEM_HELPER
    helper.write_bytes(b"synthetic protected helper")
    state = installer.receipt(root)
    state.update(scope="system", helper_sha256=installer.file_hash(helper))
    (root / installer.RECEIPT).write_text(json.dumps(state))
    monkeypatch.setattr(installer, "system_root", lambda: root)
    launched: list[Path] = []
    monkeypatch.setattr(installer, "launch_elevated_helper", launched.append)
    installer.launch_system_update(root)
    assert launched == [helper]
    helper.write_bytes(b"changed")
    with pytest.raises(ProjectError, match="missing or changed"):
        installer.launch_system_update(root)
    with pytest.raises(ProjectError, match="Program Files"):
        installer.launch_system_update(tmp_path / "user-controlled")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows system installation")
@pytest.mark.parametrize("fail_receipt", [False, True])
def test_system_install_updates_or_restores_its_helper(
    candidate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_receipt: bool
) -> None:
    root = tmp_path / "protected"
    monkeypatch.setattr(installer, "system_root", lambda: root)
    installer.install(candidate, root, "system", installer.file_hash(candidate))
    helper = root / installer.SYSTEM_HELPER
    old_helper = helper.read_bytes()
    old_state = installer.receipt(root)
    assert old_state["helper_sha256"] == installer.file_hash(helper)
    resources = tmp_path / "resources"
    (resources / "install_scripts").mkdir(parents=True)
    (resources / "install_scripts" / installer.SYSTEM_HELPER).write_bytes(
        b"synthetic next helper"
    )
    monkeypatch.setattr(installer, "files", lambda package: resources)
    candidate.write_bytes(b"next executable")
    replace = Path.replace

    def replace_receipt(path: Path, destination: Path) -> Path:
        if fail_receipt and path.name == "installation.pending.json":
            raise OSError("receipt blocked")
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", replace_receipt)
    if fail_receipt:
        with pytest.raises(OSError, match="receipt blocked"):
            installer.install(candidate, root, "system", installer.file_hash(candidate))
        assert helper.read_bytes() == old_helper
        assert installer.receipt(root) == old_state
    else:
        installer.install(candidate, root, "system", installer.file_hash(candidate))
        assert helper.read_bytes() == b"synthetic next helper"
        assert installer.receipt(root)["helper_sha256"] == installer.file_hash(helper)
    assert (root / (installer.SYSTEM_HELPER + ".previous")).read_bytes() == old_helper

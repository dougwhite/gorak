from pathlib import Path
from typing import Any

import pytest

from gorak import file_updates
from gorak.project import ProjectError


def test_apply_failure_restores_written_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"old first")
    second.write_bytes(b"old second")
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    original = Path.replace

    def replacing(path: Path, destination: Any) -> Path:
        if destination == second:
            raise OSError("disk error")
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", replacing)
    with pytest.raises(OSError):
        file_updates.apply_files(
            tmp_path, {first: b"new first", second: b"new second"}, recovery
        )
    assert first.read_bytes() == b"old first"
    assert second.read_bytes() == b"old second"
    assert (recovery / "before/first").read_bytes() == b"old first"


def test_install_checks_the_prepared_snapshot(tmp_path: Path) -> None:
    import hashlib

    path = tmp_path / "source.w4gl"
    path.write_bytes(b"new external edit")
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    with pytest.raises(ProjectError, match="before pull installation"):
        file_updates.apply_files(
            tmp_path,
            {path: b"database version"},
            recovery,
            {"source.w4gl": hashlib.sha256(b"old local version").hexdigest()},
        )
    assert path.read_bytes() == b"new external edit"


@pytest.mark.parametrize("file_count", [1, 520])
def test_fingerprint_hashes_bytes_even_when_size_and_mtime_are_unchanged(
    tmp_path: Path,
    file_count: int,
) -> None:
    import os

    for index in range(file_count - 1):
        (tmp_path / f"other-{index}.w4gl").write_bytes(b"RETURN 0;")

    source = tmp_path / "proc.w4gl"
    source.write_bytes(b"RETURN 1;")
    stat = source.stat()
    before = file_updates.fingerprint(tmp_path)
    source.write_bytes(b"RETURN 2;")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert source.stat().st_size == stat.st_size
    assert source.stat().st_mtime_ns == stat.st_mtime_ns
    assert file_updates.fingerprint(tmp_path) != before


def test_parallel_fingerprint_propagates_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(520):
        (tmp_path / f"proc-{index}.w4gl").write_bytes(b"RETURN 0;")
    digest = file_updates.file_digest

    def failing(path: Path) -> str:
        if path.name == "proc-300.w4gl":
            raise OSError("Source became unreadable")
        return digest(path)

    monkeypatch.setattr(file_updates, "file_digest", failing)
    with pytest.raises(OSError, match="Source became unreadable"):
        file_updates.fingerprint(tmp_path)


def test_fingerprint_prunes_ignored_trees_but_keeps_baselines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import os

    for directory in [".git/objects/deep", ".openroad/pulls/operation/stage"]:
        (tmp_path / directory).mkdir(parents=True)
        (tmp_path / directory / "ignored").write_text("not source")
    baseline = tmp_path / ".openroad/example/example.xml"
    baseline.parent.mkdir()
    baseline.write_bytes(b"<OPENROAD/>")
    source = tmp_path / "example/proc.w4gl"
    source.parent.mkdir()
    source.write_bytes(b"RETURN 1;")
    scandir = os.scandir

    def scanning(path: Any) -> Any:
        relative = Path(path).relative_to(tmp_path)
        assert not relative.parts or relative.parts[0] != ".git"
        assert relative.parts[:3] != (".openroad", "pulls", "operation")
        return scandir(path)

    monkeypatch.setattr(os, "scandir", scanning)
    assert file_updates.fingerprint(tmp_path) == {
        ".openroad/example/example.xml": hashlib.sha256(b"<OPENROAD/>").hexdigest(),
        "example/proc.w4gl": hashlib.sha256(b"RETURN 1;").hexdigest(),
    }


@pytest.mark.parametrize("directory", [False, True])
def test_fingerprint_rejects_source_symlinks(tmp_path: Path, directory: bool) -> None:
    target = tmp_path / "target"
    if directory:
        target.mkdir()
    else:
        target.write_text("source")
    (tmp_path / "linked").symlink_to(target, target_is_directory=directory)
    with pytest.raises(ProjectError, match="symlinked project source: linked"):
        file_updates.fingerprint(tmp_path)


def test_fingerprint_preserves_excluded_top_level_symlink_behavior(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (root / ".git").symlink_to(external, target_is_directory=True)
    (root / ".openroad").symlink_to(external, target_is_directory=True)
    assert file_updates.fingerprint(root) == {}

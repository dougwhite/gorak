import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from gorak.errors import ProjectError
from gorak.writer_launch import (
    build_writer_archive,
    local_writer_command,
    remote_writer_prefix,
)


def test_archive_is_deterministic_and_contains_production_worker(
    tmp_path: Path,
) -> None:
    a, b = tmp_path / "a.pyz", tmp_path / "b.pyz"
    build_writer_archive(a)
    build_writer_archive(b)
    assert a.read_bytes() == b.read_bytes()
    with ZipFile(a) as archive:
        assert "gorak/writer_settings.py" in archive.namelist()
    assert (
        subprocess.run(
            [sys.executable, str(a), "--help"], capture_output=True
        ).returncode
        == 0
    )


def test_disabled_launch_unchanged_and_enabled_arguments_are_separate() -> None:
    command = ["w4gldev", "rundbapp", "node::source", "app"]
    assert local_writer_command(command, None, "cp1252") is command
    wrapped = local_writer_command(command, "source", "cp1252")
    assert wrapped[-3:] == command[1:]
    assert remote_writer_prefix(None, "cp1252") == ""
    with pytest.raises(ProjectError):
        remote_writer_prefix("source&other", "cp1252")


@pytest.mark.parametrize("arguments", [["-c", "pass"], ["-m", "gorak.writer_worker"]])
def test_subprocess_guard_rejects_unbounded_python(arguments: list[str]) -> None:
    with pytest.raises(AssertionError, match="Tests must mock external commands"):
        subprocess.run([sys.executable, *arguments], check=True)

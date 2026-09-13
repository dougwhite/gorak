from pathlib import Path

import pytest
from pytest import MonkeyPatch

from gorak import app_scaffold
from gorak.project import GorakProject, ProjectError, write_json


def test_invalid_test_config_leaves_no_partial_app(tmp_path: Path) -> None:
    manifest = tmp_path / "gorak.json"
    manifest.write_text('{"name":"demo","tests":false}')
    with pytest.raises(ProjectError, match="array"):
        app_scaffold.create_application(
            GorakProject(tmp_path, "demo"), "tests", test=True
        )
    assert not (tmp_path / "tests").exists()


def test_manifest_failure_rolls_back_scaffold(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    manifest = tmp_path / "gorak.json"
    manifest.write_text('{"name":"demo"}')
    original = write_json

    def fail_manifest(path: Path, data: dict[str, object]) -> None:
        if path.name.startswith(".gorak-manifest-"):
            raise OSError("cannot write manifest")
        original(path, data)

    monkeypatch.setattr(app_scaffold, "write_json", fail_manifest)
    with pytest.raises(ProjectError, match="manifest"):
        app_scaffold.create_application(
            GorakProject(tmp_path, "demo"), "tests", test=True
        )
    assert not (tmp_path / "tests").exists()
    assert manifest.read_text() == '{"name":"demo"}'

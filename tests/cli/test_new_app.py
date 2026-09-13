import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from gorak import cli


def test_scaffolds_test_app_and_preserves_manifest(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    manifest = tmp_path / "gorak.json"
    manifest.write_text('{"name":"demo","custom":true,"tests":["existing"]}')
    subfolder = tmp_path / "existing"
    subfolder.mkdir()
    monkeypatch.chdir(subfolder)
    cli.main(["new", "app", "example_tests", "--test"])
    data = json.loads(manifest.read_text())
    assert data == {
        "name": "demo",
        "custom": True,
        "tests": ["existing", {"application": "example_tests"}],
    }
    assert json.loads((tmp_path / "example_tests/app.json").read_text()) == {
        "starting_component": "",
        "description": "",
        "included_applications": [],
    }


def test_normal_app_does_not_register_tests(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    manifest = tmp_path / "gorak.json"
    manifest.write_text('{"name":"demo"}')
    monkeypatch.chdir(tmp_path)
    cli.main(["new", "app", "example"])
    assert manifest.read_text() == '{"name":"demo"}'
    assert (tmp_path / "example/app.json").exists()


@pytest.mark.parametrize(
    "name", ["../escape", "BAD-NAME", ".openroad", "existing", "EXISTING"]
)
def test_rejects_invalid_or_colliding_app(
    tmp_path: Path, monkeypatch: MonkeyPatch, name: str
) -> None:
    manifest = tmp_path / "gorak.json"
    manifest.write_text('{"name":"demo"}')
    (tmp_path / "existing").mkdir()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["new", "app", name, "--test"])
    assert manifest.read_text() == '{"name":"demo"}'


def test_requires_project(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["new", "app", "example"])
    assert not (tmp_path / "example").exists()


def test_existing_test_entry_is_not_duplicated(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    manifest = tmp_path / "gorak.json"
    manifest.write_text(
        '{"name":"demo","tests":[{"application":"Example","timeout_seconds":90}]}'
    )
    monkeypatch.chdir(tmp_path)
    cli.main(["new", "app", "example", "--test"])
    assert json.loads(manifest.read_text())["tests"] == [
        {"application": "Example", "timeout_seconds": 90}
    ]

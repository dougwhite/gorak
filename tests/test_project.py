import json
import subprocess
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pytest import CaptureFixture

from gorak.project import (
    GorakProject,
    ProjectError,
    configure_remote,
    create_project,
    find_project_root,
    load_project,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "example.skel"


def test_create_project_creates_default_project_skeleton(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], cwd: Path) -> None:
        calls.append((command, cwd))

    project = create_project(tmp_path / "example_application", run_cmd=fake_run)
    expected_manifest = json.loads((FIXTURE_ROOT / "gorak.json").read_text())
    expected_app = json.loads(
        (FIXTURE_ROOT / "example_application" / "app.json").read_text()
    )
    expected_manifest["name"] = "example_application"

    assert project == GorakProject(
        root=tmp_path / "example_application",
        name="example_application",
    )
    assert json.loads((project.root / "gorak.json").read_text()) == expected_manifest
    assert (
        json.loads((project.root / "example_application" / "app.json").read_text())
        == expected_app
    )
    assert (project.root / "example_application" / "p4_init.w4gl").read_text() == (
        FIXTURE_ROOT / "example_application" / "p4_init.w4gl"
    ).read_text()
    assert (project.root / ".env.example").read_text() == (
        FIXTURE_ROOT / ".env.example"
    ).read_text()
    assert (project.root / ".gitignore").read_text() == ".env\n.openroad/\n"
    assert calls == [(["git", "init"], project.root)]
    assert capsys.readouterr().err == ""


def test_create_project_warns_when_git_init_fails(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    def fake_run(command: list[str], cwd: Path) -> None:
        raise subprocess.CalledProcessError(returncode=1, cmd=command)

    project = create_project(tmp_path / "my_project", run_cmd=fake_run)

    assert (project.root / "gorak.json").is_file()
    assert "WARNING: git init failed" in capsys.readouterr().err


def test_create_project_allows_existing_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "my_project"
    root.mkdir()

    project = create_project(root, run_cmd=lambda command, cwd: None)

    assert project.root == root
    assert (root / "gorak.json").is_file()


def test_create_project_rejects_existing_project(tmp_path: Path) -> None:
    root = tmp_path / "my_project"
    create_project(root, run_cmd=lambda command, cwd: None)

    with pytest.raises(ProjectError, match="already exists"):
        create_project(root)


def test_create_project_rejects_existing_non_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "my_project"
    root.mkdir()
    (root / "README.md").write_text("# Existing project\n")

    with pytest.raises(ProjectError, match="must be empty"):
        create_project(root)


def test_find_project_root_finds_manifest_from_nested_directory(tmp_path: Path) -> None:
    project = create_project(tmp_path / "my_project", run_cmd=lambda command, cwd: None)
    nested = project.root / "my_project" / "subdir"
    nested.mkdir(parents=True)

    assert find_project_root(nested) == project.root


def test_find_project_root_errors_outside_project(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="No gorak project found"):
        find_project_root(tmp_path)


def test_load_project_reads_manifest(tmp_path: Path) -> None:
    root = tmp_path / "my_project"
    root.mkdir()
    (root / "gorak.json").write_text(
        json.dumps(
            {
                "name": "Custom Name",
                "version": "0.1.0",
                "description": "An example gorak project",
                "author": "Your Name",
                "contact": "your.name@example.com",
                "license": "MIT",
            }
        )
    )

    assert load_project(root) == GorakProject(root=root, name="Custom Name")


def test_configure_remote_creates_env_file(tmp_path: Path) -> None:
    project = create_project(tmp_path / "my_project", run_cmd=lambda command, cwd: None)

    env_path = configure_remote(
        project=project,
        host="windows-pc",
        user="test",
        gorak_root=r"C:\Development\gorak",
        vnode="myvnode",
        database="exampledb",
    )

    assert env_path == project.root / ".env"
    assert dotenv_values(env_path) == {
        "GORAK_BACKEND": "remote",
        "GORAK_REMOTE_HOST": "windows-pc",
        "GORAK_REMOTE_USER": "test",
        "GORAK_REMOTE_ROOT": r"C:\Development\gorak",
        "GORAK_VNODE": "myvnode",
        "GORAK_DATABASE": "exampledb",
    }


def test_configure_remote_updates_values_and_preserves_unrelated_env(
    tmp_path: Path,
) -> None:
    project = create_project(tmp_path / "my_project", run_cmd=lambda command, cwd: None)
    env_path = project.root / ".env"
    env_path.write_text("OTHER=value\nGORAK_REMOTE_HOST=old-host\n")

    configure_remote(
        project=project,
        host="windows-pc",
        user="test",
        gorak_root=r"C:\Development\gorak",
        vnode="myvnode",
        database="exampledb",
    )

    assert dotenv_values(env_path) == {
        "OTHER": "value",
        "GORAK_REMOTE_HOST": "windows-pc",
        "GORAK_BACKEND": "remote",
        "GORAK_REMOTE_USER": "test",
        "GORAK_REMOTE_ROOT": r"C:\Development\gorak",
        "GORAK_VNODE": "myvnode",
        "GORAK_DATABASE": "exampledb",
    }

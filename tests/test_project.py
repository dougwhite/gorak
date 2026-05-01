import json
from pathlib import Path

import pytest

from gorak.project import (
    GorakProject,
    ProjectError,
    create_project,
    find_project_root,
    load_project,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "example.skel"


def test_create_project_creates_default_project_skeleton(tmp_path: Path) -> None:
    project = create_project(tmp_path / "example_application")
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


def test_create_project_allows_existing_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "my_project"
    root.mkdir()

    project = create_project(root)

    assert project.root == root
    assert (root / "gorak.json").is_file()


def test_create_project_rejects_existing_project(tmp_path: Path) -> None:
    root = tmp_path / "my_project"
    create_project(root)

    with pytest.raises(ProjectError, match="already exists"):
        create_project(root)


def test_create_project_rejects_existing_non_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "my_project"
    root.mkdir()
    (root / "README.md").write_text("# Existing project\n")

    with pytest.raises(ProjectError, match="must be empty"):
        create_project(root)


def test_find_project_root_finds_manifest_from_nested_directory(tmp_path: Path) -> None:
    project = create_project(tmp_path / "my_project")
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

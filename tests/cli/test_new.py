from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak.project import GorakProject

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "fm_example_frame.xml"


class TestNewCommand:
    """Tests for the new project CLI command."""

    def test_creates_project_and_prints_path(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        monkeypatch.chdir(tmp_path)

        def fake_create_project(
            path: Path,
            init_repo: bool = True,
        ) -> GorakProject:
            calls.append((path, init_repo))
            return GorakProject(
                root=tmp_path / "my_project",
                name="my_project",
            )

        monkeypatch.setattr(cli, "create_project", fake_create_project)

        cli.main(["new", "my_project"])

        assert calls == [(Path("my_project"), True)]
        assert capsys.readouterr().out == f"{tmp_path / 'my_project'}\n"

    def test_creates_project_without_git_when_requested(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        calls: list[object] = []
        monkeypatch.chdir(tmp_path)

        def fake_create_project(
            path: Path,
            init_repo: bool = True,
        ) -> GorakProject:
            calls.append((path, init_repo))
            return GorakProject(
                root=tmp_path / "my_project",
                name="my_project",
            )

        monkeypatch.setattr(cli, "create_project", fake_create_project)

        cli.main(["new", "--nogit", "my_project"])

        assert calls == [(Path("my_project"), False)]
        assert capsys.readouterr().out == f"{tmp_path / 'my_project'}\n"

    def test_requires_project_name(self, capsys: CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as ex:
            cli.main(["new"])

        assert ex.value.code == 2
        assert "the following arguments are required: name" in capsys.readouterr().err

    def test_errors_inside_existing_project(
        self,
        monkeypatch: MonkeyPatch,
        tmp_path: Path,
        capsys: CaptureFixture[str],
    ) -> None:
        project_root = tmp_path / "my_project"
        project_root.mkdir()
        (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
        monkeypatch.chdir(project_root)

        with pytest.raises(SystemExit) as ex:
            cli.main(["new", "another_project"])

        assert ex.value.code == 1
        assert "Cannot create a gorak project inside existing project" in (
            capsys.readouterr().err
        )

from pathlib import Path

from pytest import CaptureFixture, MonkeyPatch

from gorak import cli


def test_defaults_flatten_promotes_shared_app_defaults(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    project_root = tmp_path / "my_project"
    project_root.mkdir()
    (project_root / "gorak.json").write_text('{"name": "my_project"}\n')
    (project_root / "field_defaults.json").write_text("{}\n")
    for app_name in ["orders", "billing"]:
        app_dir = project_root / app_name
        app_dir.mkdir()
        (app_dir / "app.json").write_text("{}\n")
        (app_dir / "field_defaults.json").write_text(
            '{"common_model_container": {"properties": {"bgcolor": "70"}}}\n'
        )
    monkeypatch.chdir(project_root)

    cli.main(["defaults", "flatten"])

    assert capsys.readouterr().out == (
        "Flattened 1 field default value across 2 applications\n"
    )
    assert (project_root / "orders" / "field_defaults.json").read_text() == "{}\n"

import json
from pathlib import Path

import pytest

from gorak.cli import main
from gorak.encoded_graph import UnsupportedSource
from gorak.storage_directory import write_directory
from tests.test_storage_archive import archive


def test_source_verify_runs_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "source"
    write_directory(archive(), directory)
    monkeypatch.chdir(tmp_path)
    main(["source", "verify", str(directory)])
    assert json.loads(capsys.readouterr().out)["archive_valid"]


def test_source_verify_rejects_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "source"
    write_directory(archive(), directory)
    next((directory / "objects").iterdir()).write_text("corrupt")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["source", "verify", str(directory)])
    assert exc.value.code == 1
    assert "archive operation refused" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args", [["verify", "--dry-run"], ["restore", "--app", "sample"]]
)
def test_rejects_inapplicable_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["source", args[0], str(tmp_path / "archive"), *args[1:]])
    assert exc.value.code == 1


def test_restore_failure_is_a_clean_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak import storage_command
    from gorak.connection import OpenRoadConnection
    from tests.test_storage_restore import SETTINGS

    directory = tmp_path / "source"
    write_directory(archive(), directory)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        storage_command,
        "resolve_openroad_connection",
        lambda *_: OpenRoadConnection(
            backend="local",
            vnode="",
            database="database",
            remote_host=None,
            sql_backend="odbc",
            odbc_settings=SETTINGS,
        ),
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise UnsupportedSource("source_restore_requires_empty_database")

    monkeypatch.setattr(storage_command, "restore", fail)
    with pytest.raises(SystemExit) as exc:
        main(["source", "restore", str(directory)])
    assert exc.value.code == 1
    assert "source_restore_requires_empty_database" in capsys.readouterr().err

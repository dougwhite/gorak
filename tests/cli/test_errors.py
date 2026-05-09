import pyodbc
from pytest import CaptureFixture, MonkeyPatch
from sqlalchemy.exc import OperationalError

from gorak import cli
from gorak.local import LocalCommandError
from gorak.remote import RemoteCommandError


def test_cli_formats_local_backend_errors(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "read_applications",
        lambda connection: (_ for _ in ()).throw(
            LocalCommandError(
                "Local command failed with exit code 1\n"
                "bad stdout\n"
                "** WARNING: ignored noise\n"
                "bad stderr"
            )
        ),
    )

    try:
        cli.main(["app", "list", "--vnode", "vnode", "--database", "db"])
    except SystemExit as ex:
        assert ex.code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "ERROR: Local backend error\n"
        "Local command failed with exit code 1\n"
        "bad stdout\n"
        "bad stderr\n"
    )


def test_cli_formats_remote_backend_errors(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "read_applications",
        lambda connection: (_ for _ in ()).throw(
            RemoteCommandError(
                "Remote command failed with exit code 255\n"
                "** WARNING: ignored noise\n"
                "ssh: Could not resolve hostname windows-dev"
            )
        ),
    )

    try:
        cli.main(
            [
                "app",
                "list",
                "--backend",
                "remote",
                "--user",
                "test-user",
                "--host",
                "windows-dev",
                "--gorak-root",
                r"C:\Development\gorak",
                "--vnode",
                "vnode",
                "--database",
                "db",
            ]
        )
    except SystemExit as ex:
        assert ex.code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "ERROR: Remote backend error\n"
        "Remote command failed with exit code 255\n"
        "ssh: Could not resolve hostname windows-dev\n"
    )


def test_cli_formats_odbc_backend_errors(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "read_applications",
        lambda connection: (_ for _ in ()).throw(
            OperationalError(
                "select 1",
                {},
                pyodbc.Error("ODBC driver could not connect"),
            )
        ),
    )

    try:
        cli.main(
            [
                "app",
                "list",
                "--sql-backend",
                "odbc",
                "--vnode",
                "vnode",
                "--database",
                "db",
                "--db-driver",
                "Ingres AC",
                "--db-host",
                "db-host",
                "--db-listen-address",
                "II7",
                "--db-user",
                "ingres",
                "--db-password",
                "secret",
            ]
        )
    except SystemExit as ex:
        assert ex.code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("ERROR: ODBC backend error\n")
    assert "ODBC driver could not connect" in captured.err


def test_cli_formats_missing_command_errors(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "read_applications",
        lambda connection: (_ for _ in ()).throw(FileNotFoundError("sql")),
    )

    try:
        cli.main(["app", "list", "--vnode", "vnode", "--database", "db"])
    except SystemExit as ex:
        assert ex.code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ERROR: Command not found: sql\n"

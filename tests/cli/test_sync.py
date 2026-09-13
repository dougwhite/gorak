from collections.abc import Callable
from pathlib import Path
from typing import cast

from pytest import CaptureFixture, MonkeyPatch

from gorak import cli
from gorak.connection import OpenRoadConnection
from gorak.project import GorakContext
from gorak.sync import SyncResult


def test_sync_command_runs_project_sync(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    project = tmp_path / "my_project"
    project.mkdir()
    (project / "gorak.json").write_text('{"name": "my_project"}\n')
    (project / ".env").write_text(
        "GORAK_BACKEND=local\n"
        "GORAK_SQL_BACKEND=odbc\n"
        "GORAK_VNODE=project-vnode\n"
        "GORAK_DATABASE=project-db\n"
        "GORAK_DB_DRIVER=Ingres AC\n"
        "GORAK_DB_HOST=db-host.example\n"
        "GORAK_DB_LISTEN_ADDRESS=II7\n"
        "GORAK_DB_USER=ingres\n"
        "GORAK_DB_PASSWORD=secret\n"
    )
    monkeypatch.chdir(project)
    calls: list[object] = []

    def fake_sync_project(
        connection: OpenRoadConnection,
        context: GorakContext,
        progress: Callable[[str], None] | None,
    ) -> SyncResult:
        calls.append((connection, context.project.root if context.project else None))
        return SyncResult(checked=2, changed=1, exported=1)

    monkeypatch.setattr(cli, "sync_project", fake_sync_project)

    cli.main(["sync"])

    connection, root = cast(tuple[object, object], calls[0])
    assert isinstance(connection, OpenRoadConnection)
    assert root == project
    assert capsys.readouterr().out == (
        "Syncing from local\n"
        "Sync complete: checked 2, changed 1, exported 1 component\n"
    )


def test_sync_push_routes_dry_run(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    from gorak import push

    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    (tmp_path / ".env").write_text(
        "GORAK_BACKEND=local\nGORAK_VNODE=node\nGORAK_DATABASE=source\n"
    )
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[Path, bool]] = []

    def fake_push(connection: OpenRoadConnection, root: Path, dry_run: bool) -> str:
        calls.append((root, dry_run))
        return "Prepared push"

    monkeypatch.setattr(push, "push_project", fake_push)
    cli.main(["sync", "--push", "--dry-run"])
    assert calls == [(tmp_path, True)]
    assert capsys.readouterr().out == "Prepared push\n"


def test_clean_push_skips_redundant_executor(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    from gorak import push, sync_guard
    from gorak.sync_plan import Change

    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    (tmp_path / ".env").write_text(
        "GORAK_BACKEND=local\nGORAK_VNODE=node\nGORAK_DATABASE=source\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sync_guard,
        "guard_sync",
        lambda *a, **k: [Change("example/proc", "unchanged", "unchanged", "unchanged")],
    )

    def unexpected(connection: OpenRoadConnection, root: Path, dry_run: bool) -> str:
        raise AssertionError("Clean comparison must not repeat push preflight")

    monkeypatch.setattr(push, "push_project", unexpected)
    cli.main(["sync", "--push"])
    assert "no changes (verified comparison)" in capsys.readouterr().out
    assert not (tmp_path / ".openroad/pushes").exists()

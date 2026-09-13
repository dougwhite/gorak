import json
from pathlib import Path
from typing import Any

import pytest

from gorak import recovery
from gorak.connection import OpenRoadConnection
from gorak.project import ProjectError
from gorak.sync_guard import save_binding
from gorak.sync_plan import Change
from gorak.xml_writer import document, new_application

CONNECTION = OpenRoadConnection("local", "node", "exampledb", None)


def setup(root: Path) -> bytes:
    (root / "gorak.json").write_text('{"name":"example"}')
    folder = root / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    save_binding(CONNECTION, root)
    (root / ".openroad/push-pending.json").write_text('{"operation":"retained"}')
    return document([new_application(folder)])


@pytest.mark.parametrize("drift", ["none", "disk", "database", "install"])
def test_recovery_only_clears_marker_after_verified_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    xml = setup(tmp_path)
    monkeypatch.setattr(recovery, "plan_project", lambda c, r: [])

    def export(c: Any, a: str, path: Path) -> None:
        path.write_bytes(
            xml
            if drift != "database"
            else xml.replace(b'name="example"', b'name="other"')
        )
        if drift == "disk":
            (tmp_path / "notes.txt").write_text("concurrent edit")

    monkeypatch.setattr(recovery, "backup_application_xml", export)
    if drift == "install":

        def fail(*args: Any, **kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(recovery, "apply_files", fail)
    marker = tmp_path / ".openroad/push-pending.json"
    if drift == "none":
        assert "verified" in recovery.recover_push(CONNECTION, tmp_path)
        assert not marker.exists()
        assert (tmp_path / ".openroad/example/example.xml").read_bytes() == xml
        assert list(
            (tmp_path / ".openroad/pushes").glob("recovery-*/previous-marker.json")
        )
    else:
        with pytest.raises((ProjectError, OSError)):
            recovery.recover_push(CONNECTION, tmp_path)
        assert json.loads(marker.read_text()) == {"operation": "retained"}
        assert not (tmp_path / ".openroad/example/example.xml").exists()
    assert not (tmp_path / ".openroad/mutation.lock").exists()


def test_partial_push_requires_explicit_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup(tmp_path)
    monkeypatch.setattr(
        recovery,
        "plan_project",
        lambda c, r: [Change("example", "push", "modified", "unchanged")],
    )
    with pytest.raises(ProjectError, match="disk and database differ"):
        recovery.recover_push(CONNECTION, tmp_path)
    assert (tmp_path / ".openroad/push-pending.json").exists()


def test_recovery_rejects_different_target(tmp_path: Path) -> None:
    setup(tmp_path)
    with pytest.raises(ProjectError, match="different configured target"):
        recovery.recover_push(
            OpenRoadConnection("local", "node", "otherdb", None), tmp_path
        )
    assert (tmp_path / ".openroad/push-pending.json").exists()


def test_cli_dispatches_push_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gorak import cli

    setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls: list[Path] = []

    def recover(connection: OpenRoadConnection, root: Path) -> str:
        assert connection.database == "exampledb"
        calls.append(root)
        return "recovered"

    monkeypatch.setattr(recovery, "recover_push", recover)
    cli.main(
        [
            "recover",
            "push",
            "--backend",
            "local",
            "--vnode",
            "node",
            "--database",
            "exampledb",
        ]
    )
    assert calls == [tmp_path]
    assert capsys.readouterr().out.strip() == "recovered"

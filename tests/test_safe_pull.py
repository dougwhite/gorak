from pathlib import Path
from typing import Any

import pytest

from gorak import safe_pull
from gorak.connection import OpenRoadConnection
from gorak.domain import Application
from gorak.project import ProjectError, load_context
from gorak.sync_plan import Change


def test_apply_failure_restores_written_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"old first")
    second.write_bytes(b"old second")
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    original = Path.replace

    def replacing(path: Path, destination: Any) -> Path:
        if destination == second:
            raise OSError("disk error")
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", replacing)
    with pytest.raises(OSError):
        safe_pull.apply_files(
            tmp_path, {first: b"new first", second: b"new second"}, recovery
        )
    assert first.read_bytes() == b"old first"
    assert second.read_bytes() == b"old second"
    assert (recovery / "before/first").read_bytes() == b"old first"


def test_deleted_database_app_removes_source_but_preserves_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    (folder / "proc.w4gl").write_text("old source")
    (folder / "notes.txt").write_text("human notes")
    cache = tmp_path / ".openroad/example"
    cache.mkdir(parents=True)
    (cache / "example.xml").write_text("<OPENROAD/>")
    monkeypatch.setattr(
        safe_pull,
        "guard_sync",
        lambda *a, **k: [Change("example", "pull", "unchanged", "deleted")],
    )
    monkeypatch.setattr(
        safe_pull,
        "baseline_inventory",
        lambda r: ({"example": object(), "example/proc": object()}, {"example"}),
    )
    monkeypatch.setattr(safe_pull, "read_applications", lambda c: [])
    safe_pull.sync_project(
        OpenRoadConnection("local", "node", "db", None), load_context(tmp_path)
    )
    assert not (folder / "app.json").exists()
    assert not (folder / "proc.w4gl").exists()
    assert (folder / "notes.txt").read_text() == "human notes"
    assert not (cache / "example.xml").exists()
    assert "example" in (tmp_path / ".openroad/tracked-applications.json").read_text()


@pytest.mark.parametrize("database_drift", [False, True])
def test_change_during_staging_aborts_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, database_drift: bool
) -> None:
    from gorak.domain import ApplicationExport

    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    source = folder / "proc.w4gl"
    source.write_text("original")
    app = Application("example", "", "")
    monkeypatch.setattr(
        safe_pull,
        "guard_sync",
        lambda *a, **k: [Change("example/proc", "pull", "unchanged", "modified")],
    )
    monkeypatch.setattr(safe_pull, "baseline_inventory", lambda r: ({}, {"example"}))
    monkeypatch.setattr(safe_pull, "read_applications", lambda c: [app])
    xml = '<OPENROAD><APPLICATION name="example"/></OPENROAD>'

    def exporting(c: Any, a: str, paths: Any, progress: Any) -> ApplicationExport:
        paths.xml_path.parent.mkdir(parents=True)
        paths.source_dir.mkdir(parents=True)
        paths.xml_path.write_text(xml)
        if not database_drift:
            source.write_text("concurrent local edit")
        return ApplicationExport(app, [])

    monkeypatch.setattr(safe_pull, "export_application_to_paths", exporting)
    monkeypatch.setattr(
        safe_pull,
        "backup_application_xml",
        lambda c, a, p: p.write_text(
            xml.replace("example", "changed") if database_drift else xml
        ),
    )
    with pytest.raises(
        ProjectError,
        match="Database source changed" if database_drift else "Local project changed",
    ):
        safe_pull.sync_project(
            OpenRoadConnection("local", "node", "db", None), load_context(tmp_path)
        )
    assert source.read_text() == (
        "original" if database_drift else "concurrent local edit"
    )
    assert not (tmp_path / ".openroad/example/example.xml").exists()


def test_install_checks_the_prepared_snapshot(tmp_path: Path) -> None:
    import hashlib

    path = tmp_path / "source.w4gl"
    path.write_bytes(b"new external edit")
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    with pytest.raises(ProjectError, match="before pull installation"):
        safe_pull.apply_files(
            tmp_path,
            {path: b"database version"},
            recovery,
            {"source.w4gl": hashlib.sha256(b"old local version").hexdigest()},
        )
    assert path.read_bytes() == b"new external edit"

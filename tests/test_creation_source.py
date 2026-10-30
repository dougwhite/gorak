"""Cold uploads retain source fidelity and concurrent-edit protection."""

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from gorak import cli, comparison_inputs, compiler, creation_source, export, push
from gorak.connection import OpenRoadConnection
from gorak.importer import signature
from gorak.portable_source import restore_application, restore_component
from gorak.project import ProjectError
from gorak.safe_pull import fingerprint
from gorak.source_xml import from_bytes, read_tree
from gorak.xml_writer import document, prepare_submission


def project(root: Path, count: int = 2) -> Path:
    (root / "gorak.json").write_text('{"name":"example"}')
    folder = root / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    for index in range(count):
        (folder / f"proc{index}.w4gl").write_text(
            f"[proc4glsource]\n===\nPROCEDURE proc{index}() = {{ /* old */ }}"
        )
    return folder


def connection() -> OpenRoadConnection:
    return OpenRoadConnection("local", "node", "source", None)


def mock_backend(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    submitted: list[bytes] = []
    monkeypatch.setattr(export, "read_applications", lambda c: [])
    monkeypatch.setattr(push, "read_applications", lambda c: [])
    monkeypatch.setattr(
        push,
        "import_component_xml",
        lambda c, a, n, p, log, **k: submitted.append(p.read_bytes()),
    )
    monkeypatch.setattr(compiler, "finish_push_compilation", lambda c, r, o, s: s)
    return submitted


def test_streamed_upload_matches_legacy_contract_preparation(tmp_path: Path) -> None:
    root = tmp_path / "project"
    shutil.copytree(Path(__file__).parents[1] / "compatibility/project", root)
    proof = fingerprint(root)
    with comparison_inputs.scope():
        for manifest in sorted(root.glob("*/app.json")):
            folder = manifest.parent
            sources = sorted(folder.glob("*.w4gl"))
            expected = from_bytes(
                document(
                    [restore_application(folder), *map(restore_component, sources)]
                )
            )
            prepare_submission(expected)
            destination = tmp_path / f"{folder.name}.xml"
            _, targets = creation_source.prepare_application(
                root, folder, sources, destination, proof
            )
            assert signature(read_tree(destination).getroot()) == signature(expected)
            assert targets == [(folder.name, p.stem) for p in sources]
    assert fingerprint(root) == proof


def test_cli_cold_upload_reconstructs_each_component_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = project(tmp_path)
    submitted = mock_backend(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *a: connection())
    decoded: list[str] = []
    original = restore_component

    def decode(path: Path) -> etree._Element:
        decoded.append(path.name)
        return original(path)

    monkeypatch.setattr(creation_source, "restore_component", decode)
    from gorak import sync_guard

    monkeypatch.setattr(
        sync_guard,
        "plan_project",
        lambda *a, **k: pytest.fail("Duplicate cold reconstruction"),
    )
    cli.sync_command(argparse.Namespace(push=True, bind=False, dry_run=False))
    assert decoded == [p.name for p in sorted(folder.glob("*.w4gl"))]
    assert len(submitted) == 1
    assert json.loads((tmp_path / ".openroad/compile-pending.json").read_text()) == [
        ["example", "proc0"],
        ["example", "proc1"],
    ]


def test_transient_live_edit_cannot_change_prepared_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = project(tmp_path, 1)
    source = folder / "proc0.w4gl"
    before = source.read_bytes()
    submitted = mock_backend(monkeypatch)
    original = restore_component

    def racing(path: Path) -> etree._Element:
        assert path != source
        source.write_bytes(before.replace(b"old", b"new"))
        try:
            return original(path)
        finally:
            source.write_bytes(before)

    monkeypatch.setattr(creation_source, "restore_component", racing)
    push.push_project(connection(), tmp_path)
    assert b"old" in submitted[0] and b"new" not in submitted[0]
    assert source.read_bytes() == before


def test_catalog_check_edit_remains_pending_after_snapshot_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    folder = project(tmp_path, 1)
    source = folder / "proc0.w4gl"
    submitted = mock_backend(monkeypatch)
    calls = 0

    def inventory(c: Any) -> list[Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            times = source.stat()
            source.write_bytes(source.read_bytes().replace(b"old", b"new"))
            os.utime(source, ns=(times.st_atime_ns, times.st_mtime_ns))
        return []

    monkeypatch.setattr(push, "read_applications", inventory)
    push.push_project(connection(), tmp_path)
    assert b"old" in submitted[0] and b"new" not in submitted[0]
    assert b"new" in source.read_bytes()
    assert (tmp_path / ".openroad/example/example.xml").read_bytes() == submitted[0]
    assert not (tmp_path / ".openroad/push-pending.json").exists()


def test_streamed_document_keeps_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = project(tmp_path)
    monkeypatch.setattr(creation_source, "MAX_DOCUMENT_BYTES", 10)
    with comparison_inputs.scope(), pytest.raises(ProjectError, match="document limit"):
        creation_source.prepare_application(
            tmp_path,
            folder,
            sorted(folder.glob("*.w4gl")),
            tmp_path / "output.xml",
            fingerprint(tmp_path),
        )


def test_cold_push_does_not_rescan_sources_during_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project(tmp_path)
    shutil.copytree(tmp_path / "example", tmp_path / "second")
    submitted = mock_backend(monkeypatch)
    scans = 0

    def scanning(root: Path) -> dict[str, str]:
        nonlocal scans
        assert not submitted, "Source scan after imports started"
        scans += 1
        return fingerprint(root)

    from gorak import safe_pull

    monkeypatch.setattr(push, "fingerprint", scanning)
    monkeypatch.setattr(safe_pull, "fingerprint", scanning)
    push.push_project(connection(), tmp_path)
    assert len(submitted) == 2
    assert scans == 2


@pytest.mark.parametrize("tracking", ["sync-target.json", "example/example.xml"])
def test_tracking_edits_during_upload_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tracking: str
) -> None:
    project(tmp_path)
    mock_backend(monkeypatch)
    target = tmp_path / ".openroad" / tracking

    def importing(*args: Any, **kwargs: Any) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"independent tracking edit")

    monkeypatch.setattr(push, "import_component_xml", importing)
    with pytest.raises(ProjectError, match="File changed before pull installation"):
        push.push_project(connection(), tmp_path)
    assert target.read_bytes() == b"independent tracking edit"
    assert (tmp_path / ".openroad/push-pending.json").exists()

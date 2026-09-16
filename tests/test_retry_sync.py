"""End-to-end source reconciliation with an in-memory OpenROAD backend."""

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from gorak import (
    cli,
    compiler,
    export,
    importer,
    push,
    push_retry,
    recovery,
    safe_pull,
    sync_plan,
)
from gorak.connection import OpenRoadConnection
from gorak.domain import Application, ComponentInfo
from gorak.importer import signature
from gorak.project import ProjectError
from gorak.sync_guard import save_binding
from gorak.xml_writer import document, new_application, new_component

CONNECTION = OpenRoadConnection("local", "node", "exampledb", None)


class World:
    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch):
        self.root = root
        self.folder = root / "example"
        self.folder.mkdir()
        (root / "gorak.json").write_text('{"name":"example"}')
        (self.folder / "app.json").write_text("{}")
        for name in ("caller", "dependency"):
            self.edit(name, "old")
        self.database = etree.fromstring(
            document(
                [
                    new_application(self.folder),
                    *[new_component(p) for p in sorted(self.folder.glob("*.w4gl"))],
                ]
            )
        )
        self.cache = root / ".openroad/example/example.xml"
        self.cache.parent.mkdir(parents=True)
        self.cache.write_bytes(etree.tostring(self.database))
        save_binding(CONNECTION, root)
        self.imports: list[str] = []
        self.compiles: list[str] = []
        self.lose_response = False
        self.compile_failure = False
        monkeypatch.chdir(root)
        monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *a: CONNECTION)
        for module in (push, push_retry, safe_pull, sync_plan):
            monkeypatch.setattr(
                module, "read_applications", lambda c: [Application("example", "", "")]
            )
        for module in (push, push_retry, safe_pull, sync_plan, recovery, export):
            monkeypatch.setattr(module, "backup_application_xml", self.export_app)
        monkeypatch.setattr(importer, "backup_component_xml", self.export_component)
        monkeypatch.setattr(
            push,
            "read_components",
            lambda c, a: [
                ComponentInfo(a, str(n.get("name")), "proc4glsource", "")
                for n in self.database.findall("COMPONENT")
            ],
        )
        monkeypatch.setattr(importer, "import_component_xml", self.import_xml)
        monkeypatch.setattr(push, "import_component_xml", self.import_xml)
        monkeypatch.setattr(compiler, "compile_source", self.compile)

    def edit(self, name: str, value: str) -> None:
        (self.folder / f"{name}.w4gl").write_text(
            f"[proc4glsource]\n===\nPROCEDURE {name}() = {{ /* {value} */ }}"
        )

    def node(self, name: str) -> etree._Element:
        return next(
            n for n in self.database.findall("COMPONENT") if n.get("name") == name
        )

    def export_app(self, c: Any, app: str, path: Path) -> None:
        path.write_bytes(etree.tostring(self.database))

    def export_component(self, c: Any, app: str, name: str, path: Path) -> None:
        path.write_bytes(document([deepcopy(self.node(name))]))

    def import_xml(
        self, c: Any, app: str, name: str, path: Path, log: Path, **kwargs: Any
    ) -> None:
        self.imports.append(name)
        for node in etree.parse(str(path)).getroot():
            old = next(
                (
                    n
                    for n in self.database
                    if n.tag == node.tag and n.get("name") == node.get("name")
                ),
                None,
            )
            if old is None:
                self.database.append(deepcopy(node))
            else:
                self.database.replace(old, deepcopy(node))
        log.write_text("Source imported")
        if self.lose_response:
            self.lose_response = False
            raise ProjectError("Connection lost after import")

    def compile(self, c: Any, app: str, name: str, log: Path) -> compiler.CompileResult:
        assert "new" in (self.node("dependency").findtext("script") or ""), (
            "Compiled before dependencies imported"
        )
        self.compiles.append(name)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "ERROR: compiler rejected source" if self.compile_failure else "Compiled"
        )
        return compiler.CompileResult(not self.compile_failure, log)

    def push(self, *, force: bool = False) -> str:
        return cli.sync_command(
            argparse.Namespace(push=True, force=force, bind=False, dry_run=False)
        )


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


def test_all_sources_import_before_compile_and_compile_failure_does_not_block(
    world: World,
) -> None:
    world.edit("caller", "new")
    world.edit("dependency", "new")
    world.compile_failure = True
    result = world.push()
    assert world.imports == ["caller", "dependency"]
    assert world.compiles == ["caller", "dependency"]
    assert "caller.w4gl failed compilation" in result
    assert "gorak compile example caller" in result
    assert not (world.root / ".openroad/push-pending.json").exists()
    assert "no changes" in world.push()
    assert len(world.imports) == 2


def test_retry_recognizes_lost_response_and_pushes_newer_disk_edits(
    world: World,
) -> None:
    world.edit("caller", "new")
    world.edit("dependency", "new")
    world.lose_response = True
    original = world.cache.read_bytes()
    with pytest.raises(ProjectError, match="Connection lost"):
        world.push()
    assert world.cache.read_bytes() == original
    assert not world.compiles
    world.edit("caller", "newer")
    world.push()
    assert world.imports == ["caller", "caller", "dependency"]
    assert "newer" in world.node("caller").findtext("script", "")
    assert not (world.root / ".openroad/push-pending.json").exists()
    assert list((world.root / ".openroad/pushes").glob("retry-*/previous-marker.json"))


def test_retry_skips_already_imported_component(world: World) -> None:
    world.edit("caller", "new")
    world.edit("dependency", "new")
    world.lose_response = True
    with pytest.raises(ProjectError):
        world.push()
    world.push()
    assert world.imports == ["caller", "dependency"]


def test_retry_does_not_overwrite_independent_database_edit(world: World) -> None:
    world.edit("caller", "new")
    world.edit("dependency", "new")
    world.lose_response = True
    with pytest.raises(ProjectError):
        world.push()
    world.node("caller").find("script").text = "independent workbench edit"
    with pytest.raises(ProjectError, match="before writes"):
        world.push()
    assert world.imports == ["caller"]
    assert world.node("caller").findtext("script") == "independent workbench edit"
    world.push(force=True)
    assert "new" in world.node("caller").findtext("script", "")
    assert not (world.root / ".openroad/push-pending.json").exists()
    assert any(
        b"independent workbench edit" in p.read_bytes()
        for p in (world.root / ".openroad/pushes").glob("force-*/example.xml")
    )


def test_force_repairs_corrupt_baseline_and_preserves_it(world: World) -> None:
    world.edit("caller", "new")
    world.edit("dependency", "new")
    world.cache.write_bytes(b"broken XML baseline")
    marker = world.root / ".openroad/push-pending.json"
    marker.write_text("broken marker")
    result = world.push(force=True)
    assert "Push complete" in result
    assert not marker.exists()
    assert list((world.root / ".openroad/pushes").glob("force-*/resolved"))
    assert any(
        p.read_bytes() == b"broken XML baseline"
        for p in (world.root / ".openroad/pushes").glob(
            "force-*/before/.openroad/example/example.xml"
        )
    )


def test_recovery_take_database_preserves_displaced_disk(world: World) -> None:
    world.edit("caller", "disk-only change")
    world.edit("local_only", "local addition")
    (world.folder / "notes.txt").write_text("keep human notes")
    (world.root / ".openroad/push-pending.json").write_text("broken marker")
    result = recovery.recover_push(CONNECTION, world.root, take="database")
    assert "Recovery took database source" in result
    assert "disk-only change" not in (world.folder / "caller.w4gl").read_text()
    assert not (world.folder / "local_only.w4gl").exists()
    assert (world.folder / "notes.txt").read_text() == "keep human notes"
    assert any(
        "disk-only change" in p.read_text()
        for p in (world.root / ".openroad/pushes").glob(
            "force-*/source/example/caller.w4gl"
        )
    )
    assert not world.imports


def test_force_does_not_override_target_binding(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "resolve_openroad_connection",
        lambda *a: OpenRoadConnection("local", "node", "otherdb", None),
    )
    with pytest.raises(ProjectError, match="different configured target"):
        world.push(force=True)
    assert not world.imports


def test_force_refuses_invalid_source_without_clearing_recovery(world: World) -> None:
    (world.folder / "caller.w4gl").write_text("invalid source")
    with pytest.raises((ProjectError, ValueError)):
        world.push(force=True)
    marker = json.loads((world.root / ".openroad/push-pending.json").read_text())
    assert marker["state"] == "recovery_required"
    assert not world.imports


def test_recovery_take_disk_updates_source_and_clears_marker(world: World) -> None:
    world.edit("caller", "new")
    world.edit("dependency", "new")
    (world.root / ".openroad/push-pending.json").write_text("broken marker")
    assert "Push complete" in recovery.recover_push(CONNECTION, world.root, take="disk")
    assert not (world.root / ".openroad/push-pending.json").exists()
    assert world.imports == ["caller", "dependency"]


def test_failed_verification_requires_explicit_recovery(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.edit("caller", "new")
    world.edit("dependency", "new")
    original = world.import_xml

    def corrupt(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        world.node("caller").find("script").text = "unexpected database source"

    monkeypatch.setattr(importer, "import_component_xml", corrupt)
    with pytest.raises(ProjectError, match="verification failed"):
        world.push()
    marker = world.root / ".openroad/push-pending.json"
    assert json.loads(marker.read_text())["state"] == "recovery_required"
    with pytest.raises(ProjectError, match="requires recovery"):
        world.push()
    monkeypatch.setattr(importer, "import_component_xml", world.import_xml)
    world.push(force=True)
    assert not marker.exists()


def test_recovery_verification_uses_baseline_preserving_comparison(
    world: World,
) -> None:
    # Empty exported structure is intentionally absent from compact metadata.
    app_node = world.database.find("APPLICATION")
    etree.SubElement(app_node, "extension")
    world.cache.write_bytes(etree.tostring(world.database))
    marker = world.root / ".openroad/push-pending.json"
    marker.write_text('{"operation":"legacy evidence"}')
    assert "Push recovery verified" in recovery.recover_push(CONNECTION, world.root)
    assert not marker.exists()
    assert signature(etree.fromstring(world.cache.read_bytes())) == signature(
        world.database
    )


def test_force_preserves_pull_installation_evidence(world: World) -> None:
    world.edit("caller", "new")
    world.edit("dependency", "new")
    pending = world.root / ".openroad/pull-pending.json"
    pending.write_text('{"operation":"retained failed pull"}')
    world.push(force=True)
    assert not pending.exists()
    assert any(
        "retained failed pull" in p.read_text()
        for p in (world.root / ".openroad/pushes").glob(
            "force-*/previous-pull-marker.json"
        )
    )


def test_read_only_status_reports_pending_push(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = world.root / ".openroad/push-pending.json"
    marker.write_text('{"operation":"old attempt","state":"retryable"}')
    before = world.cache.read_bytes()
    cli.main(["status"])
    result = json.loads(capsys.readouterr().out)
    assert result["source_operation"]["state"] == "retryable"
    assert result["changes"] == []
    assert world.cache.read_bytes() == before
    assert marker.exists()


def test_status_explains_unavailable_comparison_when_baseline_broken(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    (world.root / ".openroad/push-pending.json").write_text("broken marker")
    world.cache.write_text("broken baseline")
    cli.main(["status"])
    result = json.loads(capsys.readouterr().out)
    assert result["observation"]["comparison_available"] is False
    assert result["source_operation"]["state"] == "recovery_required"


def test_force_rechecks_database_after_displaced_snapshot(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = world.export_app

    def changed(c: Any, app: str, path: Path) -> None:
        world.node("caller").find(
            "script"
        ).text = "concurrent edit after force snapshot"
        original(c, app, path)

    monkeypatch.setattr(sync_plan, "backup_application_xml", changed)
    with pytest.raises(ProjectError, match="before writes"):
        world.push(force=True)
    assert not world.imports
    assert (world.root / ".openroad/push-pending.json").exists()


def test_force_never_deletes_database_only_components(world: World) -> None:
    (world.folder / "caller.w4gl").unlink()
    world.edit("dependency", "new")
    world.push(force=True)
    assert world.node("caller") is not None
    assert world.imports == ["dependency"]


def test_retry_compiles_component_imported_by_previous_attempt(world: World) -> None:
    world.edit("caller", "new")
    world.edit("dependency", "new")
    world.lose_response = True
    with pytest.raises(ProjectError):
        world.push()
    assert world.compiles == []
    world.push()
    assert world.imports == ["caller", "dependency"]
    assert set(world.compiles) == {"caller", "dependency"}


def test_retry_after_interrupted_baseline_install_uses_original_snapshot(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.edit("caller", "new")
    world.edit("dependency", "new")
    real_apply = safe_pull.apply_files

    def interrupted(*args: Any, **kwargs: Any) -> None:
        world.cache.unlink()
        raise KeyboardInterrupt("simulated process interruption during installation")

    monkeypatch.setattr(push, "apply_files", interrupted)
    with pytest.raises(KeyboardInterrupt):
        world.push()
    marker = world.root / ".openroad/push-pending.json"
    assert json.loads(marker.read_text())["state"] == "retryable"
    monkeypatch.setattr(push, "apply_files", real_apply)
    world.push()
    assert world.cache.exists()
    assert not marker.exists()
    assert world.imports == ["caller", "dependency"]
    assert set(world.compiles) == {"caller", "dependency"}


def test_force_does_not_override_revision_quarantine(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    generation = "12345678-1234-1234-1234-123456789abc"
    connection = replace(CONNECTION, revision_generation=generation)
    monkeypatch.setattr(cli, "resolve_openroad_connection", lambda *a: connection)
    (world.root / ".openroad/revision-quarantine.json").write_text(
        json.dumps({"generation": generation})
    )
    with pytest.raises(ProjectError, match="quarantined"):
        world.push(force=True)
    assert not world.imports


def test_force_cannot_override_active_writer(world: World) -> None:
    from gorak.project_lock import project_lock

    with project_lock(world.root, "active writer"):
        with pytest.raises(ProjectError, match="may be active"):
            world.push(force=True)
    assert not world.imports


def test_retry_adopts_application_created_before_lost_response(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.cache.unlink()
    world.edit("caller", "new")
    world.edit("dependency", "new")
    available = [False]

    def apps(c: Any) -> list[Application]:
        return [Application("example", "", "")] if available[0] else []

    for module in (push, push_retry, safe_pull, sync_plan):
        monkeypatch.setattr(module, "read_applications", apps)
    original = world.import_xml

    def importing(*args: Any, **kwargs: Any) -> None:
        available[0] = True
        original(*args, **kwargs)

    monkeypatch.setattr(push, "import_component_xml", importing)
    world.lose_response = True
    with pytest.raises(ProjectError, match="Connection lost"):
        world.push()
    world.push()
    assert world.imports == ["-"]
    assert world.cache.exists()
    assert set(world.compiles) == {"caller", "dependency"}


def test_legacy_v8_pending_attempt_is_reconciled_without_reconstruction(
    world: World,
) -> None:
    import shutil

    world.edit("caller", "new")
    world.edit("dependency", "new")
    world.lose_response = True
    with pytest.raises(ProjectError):
        world.push()
    marker = world.root / ".openroad/push-pending.json"
    operation = Path(json.loads(marker.read_text())["operation"])
    marker.write_text(json.dumps({"operation": str(operation)}))
    shutil.rmtree(operation / "submitted")
    world.push()
    assert world.imports == ["caller", "dependency"]
    assert not marker.exists()


def test_force_rejects_incomplete_export_before_replacing_baseline(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = world.cache.read_bytes()

    def incomplete(c: Any, app: str, path: Path) -> None:
        path.write_bytes(document([deepcopy(world.node("caller"))]))

    monkeypatch.setattr(push_retry, "backup_application_xml", incomplete)
    with pytest.raises(ProjectError, match="Invalid application export"):
        world.push(force=True)
    assert world.cache.read_bytes() == before
    assert not world.imports

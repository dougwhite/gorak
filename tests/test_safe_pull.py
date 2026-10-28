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


@pytest.mark.parametrize("sidecar", ["proc.fielddefaults.json", "proc.queries.json"])
def test_deleted_database_app_removes_source_but_preserves_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sidecar: str
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    (folder / "proc.w4gl").write_text("old source")
    (folder / sidecar).write_text('{"field_styles": []}')
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
    from gorak.operation_progress import progress_scope

    messages: list[str] = []
    with progress_scope("Sync", messages.append):
        safe_pull.sync_project(
            OpenRoadConnection("local", "node", "db", None), load_context(tmp_path)
        )
    assert any("Installing verified source files" in message for message in messages)
    assert any("Source installation: 100%" in message for message in messages)
    assert not (folder / "app.json").exists()
    assert not (folder / "proc.w4gl").exists()
    assert not (folder / sidecar).exists()
    assert (
        len(list((tmp_path / ".openroad/pulls").glob(f"*/before/example/{sidecar}")))
        == 1
    )
    assert (folder / "notes.txt").read_text() == "human notes"
    assert not (cache / "example.xml").exists()
    assert "example" in (tmp_path / ".openroad/tracked-applications.json").read_text()


@pytest.mark.parametrize("database_drift", [False, True])
def test_change_during_staging_aborts_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, database_drift: bool
) -> None:
    from gorak import export
    from gorak.domain import ApplicationExport

    monkeypatch.setattr(export, "read_components", lambda *a: [])

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

    def exporting(
        c: Any, a: str, paths: Any, progress: Any, **kwargs: Any
    ) -> ApplicationExport:
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


def test_xml_verification_skips_parsing_identical_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.xml"
    second = tmp_path / "second.xml"
    xml = '<OPENROAD><COMPONENT name="proc"><script>RETURN 1;</script></COMPONENT></OPENROAD>'
    first.write_text(xml)
    second.write_text(xml)

    def unexpected_parse(path: Path) -> Any:
        raise AssertionError("Identical validated XML needs no further parsing")

    monkeypatch.setattr(safe_pull, "read_document", unexpected_parse)
    assert safe_pull.same_xml(first, second)


def test_xml_verification_falls_back_for_formatting_and_detects_source_drift(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.xml"
    second = tmp_path / "second.xml"
    first.write_text(
        '<OPENROAD><COMPONENT name="proc"><script>RETURN 1;</script></COMPONENT></OPENROAD>'
    )
    second.write_text(
        '<OPENROAD>\n  <COMPONENT name="proc">\n    <script>RETURN 1;</script>\n  </COMPONENT>\n</OPENROAD>\n'
    )
    assert safe_pull.same_xml(first, second)
    second.write_text(second.read_text().replace("RETURN 1;", "RETURN 2;"))
    assert not safe_pull.same_xml(first, second)


def test_fingerprint_hashes_bytes_even_when_size_and_mtime_are_unchanged(
    tmp_path: Path,
) -> None:
    import os

    source = tmp_path / "proc.w4gl"
    source.write_bytes(b"RETURN 1;")
    stat = source.stat()
    before = safe_pull.fingerprint(tmp_path)
    source.write_bytes(b"RETURN 2;")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert source.stat().st_size == stat.st_size
    assert source.stat().st_mtime_ns == stat.st_mtime_ns
    assert safe_pull.fingerprint(tmp_path) != before


def test_fingerprint_prunes_ignored_trees_but_keeps_baselines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import os

    for directory in [".git/objects/deep", ".openroad/pulls/operation/stage"]:
        (tmp_path / directory).mkdir(parents=True)
        (tmp_path / directory / "ignored").write_text("not source")
    baseline = tmp_path / ".openroad/example/example.xml"
    baseline.parent.mkdir()
    baseline.write_bytes(b"<OPENROAD/>")
    source = tmp_path / "example/proc.w4gl"
    source.parent.mkdir()
    source.write_bytes(b"RETURN 1;")
    scandir = os.scandir

    def scanning(path: Any) -> Any:
        relative = Path(path).relative_to(tmp_path)
        assert not relative.parts or relative.parts[0] != ".git"
        assert relative.parts[:3] != (".openroad", "pulls", "operation")
        return scandir(path)

    monkeypatch.setattr(os, "scandir", scanning)
    assert safe_pull.fingerprint(tmp_path) == {
        ".openroad/example/example.xml": hashlib.sha256(b"<OPENROAD/>").hexdigest(),
        "example/proc.w4gl": hashlib.sha256(b"RETURN 1;").hexdigest(),
    }


@pytest.mark.parametrize("directory", [False, True])
def test_fingerprint_rejects_source_symlinks(tmp_path: Path, directory: bool) -> None:
    target = tmp_path / "target"
    if directory:
        target.mkdir()
    else:
        target.write_text("source")
    (tmp_path / "linked").symlink_to(target, target_is_directory=directory)
    with pytest.raises(ProjectError, match="symlinked project source: linked"):
        safe_pull.fingerprint(tmp_path)


def test_fingerprint_preserves_excluded_top_level_symlink_behavior(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (root / ".git").symlink_to(external, target_is_directory=True)
    (root / ".openroad").symlink_to(external, target_is_directory=True)
    assert safe_pull.fingerprint(root) == {}


@pytest.mark.parametrize("take_database", [False, True])
@pytest.mark.parametrize("database_drift", [False, True])
def test_pull_reuses_planning_export_and_rechecks_database_before_installing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    take_database: bool,
    database_drift: bool,
) -> None:
    from lxml import etree

    from gorak import export, sync_plan
    from gorak.domain import ComponentInfo
    from gorak.sync_guard import save_binding
    from gorak.xml_writer import document, new_application, new_component

    connection = OpenRoadConnection("local", "node", "db", None)
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    source = folder / "proc.w4gl"
    source.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    original_source = source.read_bytes()
    baseline = tmp_path / ".openroad/example/example.xml"
    baseline.parent.mkdir(parents=True)
    native = etree.fromstring(
        document([new_application(folder), new_component(source)])
    )
    original_xml = etree.tostring(native)
    baseline.write_bytes(original_xml)
    save_binding(connection, tmp_path)
    component = native.find("COMPONENT")
    assert component is not None
    script = component.find("script")
    assert script is not None
    script.text = "RETURN 2;"
    exports: list[str] = []

    def exporting(c: Any, app: str, path: Path) -> None:
        exports.append(app)
        if database_drift and len(exports) == 2:
            script.text = "RETURN 3;"
        path.write_bytes(etree.tostring(native))

    for module in (safe_pull, sync_plan):
        monkeypatch.setattr(module, "backup_application_xml", exporting)
        monkeypatch.setattr(
            module, "read_applications", lambda c: [Application("example", "", "")]
        )
    monkeypatch.setattr(
        export,
        "read_components",
        lambda c, a: [ComponentInfo(a, "proc", "proc4glsource", "")],
    )
    if database_drift:
        with pytest.raises(ProjectError, match="Database source changed during pull"):
            safe_pull._sync_project(
                connection, tmp_path, None, take_database=take_database
            )
        assert source.read_bytes() == original_source
        assert baseline.read_bytes() == original_xml
    else:
        result = safe_pull._sync_project(
            connection, tmp_path, None, take_database=take_database
        )
        assert result.exported == 1
        assert "RETURN 2;" in source.read_text()
    assert exports == ["example", "example"]


@pytest.mark.parametrize("mutation", ["delete", "add", "edit", "binding"])
def test_pull_checks_planning_changes_and_allows_initial_target_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    from gorak.sync_guard import save_binding

    connection = OpenRoadConnection("local", "node", "db", None)
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    source = tmp_path / "notes.txt"
    source.write_text("original")

    def planning(*args: Any, **kwargs: Any) -> list[Change]:
        if mutation == "delete":
            source.unlink()
        elif mutation == "add":
            (tmp_path / "new.txt").write_text("added")
        elif mutation == "edit":
            source.write_text("modified")
        else:
            save_binding(connection, tmp_path)
        return []

    monkeypatch.setattr(safe_pull, "guard_sync", planning)
    monkeypatch.setattr(safe_pull, "read_applications", lambda c: [])
    if mutation == "binding":
        result = safe_pull.sync_project(connection, load_context(tmp_path))
        assert result.exported == 0
        assert (tmp_path / ".openroad/sync-target.json").is_file()
    else:
        with pytest.raises(ProjectError, match="Project changed while planning pull"):
            safe_pull.sync_project(connection, load_context(tmp_path))


def test_unchanged_pull_does_not_leave_captured_xml_or_recovery_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import export, sync_plan
    from gorak.sync_guard import save_binding
    from gorak.xml_writer import document, new_application

    connection = OpenRoadConnection("local", "node", "db", None)
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    baseline = tmp_path / ".openroad/example/example.xml"
    baseline.parent.mkdir(parents=True)
    xml = document([new_application(folder)])
    baseline.write_bytes(xml)
    save_binding(connection, tmp_path)
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()}
    exports: list[str] = []

    def exporting(c: Any, app: str, path: Path) -> None:
        exports.append(app)
        path.write_bytes(xml)

    for module in (safe_pull, sync_plan):
        monkeypatch.setattr(module, "backup_application_xml", exporting)
        monkeypatch.setattr(
            module, "read_applications", lambda c: [Application("example", "", "")]
        )
    monkeypatch.setattr(export, "read_components", lambda *a: [])
    result = safe_pull.sync_project(connection, load_context(tmp_path))
    assert result.exported == 0
    assert exports == ["example"]
    assert {
        p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()
    } == before | {Path(".openroad/comparison-cache.json")}


@pytest.mark.parametrize("local_edit", [False, True])
@pytest.mark.parametrize("database_drift", [False, True])
def test_fresh_clone_adopts_matching_xml_without_rewriting_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_edit: bool,
    database_drift: bool,
) -> None:
    from gorak import export, sync_plan
    from gorak.domain import ComponentInfo
    from gorak.xml_writer import document, new_application, new_component

    connection = OpenRoadConnection("local", "node", "db", None)
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{ }\n")
    source = folder / "proc.w4gl"
    source.write_text('[proc4glsource]\ndatatype = "integer"\n===\nRETURN 1;')
    xml = document([new_application(folder), new_component(source)])
    if local_edit:
        source.write_text(source.read_text().replace("RETURN 1", "RETURN 2"))
    before = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    exports: list[str] = []

    def exporting(c: Any, app: str, path: Path) -> None:
        exports.append(app)
        path.write_bytes(
            xml.replace(b"RETURN 1;", b"RETURN 3;")
            if database_drift and len(exports) == 2
            else xml
        )

    def unexpected_projection(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Matching source must not be projected again")

    for module in (safe_pull, sync_plan):
        monkeypatch.setattr(module, "backup_application_xml", exporting)
        monkeypatch.setattr(
            module, "read_applications", lambda c: [Application("example", "", "")]
        )
    monkeypatch.setattr(export, "project_component_files", unexpected_projection)
    monkeypatch.setattr(
        export,
        "read_components",
        lambda c, a: [ComponentInfo(a, "proc", "proc4glsource", "")],
    )
    baseline = tmp_path / ".openroad/example/example.xml"
    if local_edit:
        with pytest.raises(ProjectError, match="Sync stopped before writes"):
            safe_pull.sync_project(connection, load_context(tmp_path))
        assert not baseline.exists()
        assert exports == ["example"]
    elif database_drift:
        with pytest.raises(ProjectError, match="Database source changed during pull"):
            safe_pull.sync_project(connection, load_context(tmp_path))
        assert not baseline.exists()
        assert exports == ["example", "example"]
    else:
        result = safe_pull.sync_project(connection, load_context(tmp_path))
        assert result.exported == 1
        assert not result.failures
        assert baseline.read_bytes() == xml
        assert exports == ["example", "example"]

        def unexpected_reconstruction(path: Path) -> Any:
            raise AssertionError("Bootstrap already verified this source")

        monkeypatch.setattr(
            sync_plan, "comparison_component", unexpected_reconstruction
        )
        current_baseline, _, disk, invalid = sync_plan.local_inventory(tmp_path)
        assert current_baseline == disk
        assert not invalid
    assert before == {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file() and ".openroad" not in p.relative_to(tmp_path).parts
    }


@pytest.mark.parametrize("previous_baseline", [False, True])
@pytest.mark.parametrize("catalog_omitted", [False, True])
def test_baseline_adoption_preserves_catalog_omissions_and_full_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    previous_baseline: bool,
    catalog_omitted: bool,
) -> None:
    from copy import deepcopy

    from lxml import etree

    from gorak import export, sync_plan
    from gorak.domain import ComponentInfo
    from gorak.sync_guard import save_binding
    from gorak.xml_writer import document, new_application, new_component

    connection = OpenRoadConnection("local", "node", "db", None)
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    source = folder / "good.w4gl"
    source.write_text('[proc4glsource]\ndatatype = "integer"\n\n===\n\nRETURN 1;\n')
    application = new_application(folder)
    good = new_component(source)
    xml = document([application, good])
    baseline = tmp_path / ".openroad/example/example.xml"
    if previous_baseline:
        baseline.parent.mkdir(parents=True)
        omitted = deepcopy(good)
        omitted.set("name", "omitted")
        baseline.write_bytes(document([application, good, omitted]))
        (baseline.parent / "omitted.xml").write_bytes(document([omitted]))
        save_binding(connection, tmp_path)
    for module in (safe_pull, sync_plan):
        monkeypatch.setattr(
            module, "backup_application_xml", lambda c, a, p: p.write_bytes(xml)
        )
        monkeypatch.setattr(
            module, "read_applications", lambda c: [Application("example", "", "")]
        )
    catalog_reads = 0

    def catalog(c: Any, app: str) -> list[ComponentInfo]:
        nonlocal catalog_reads
        catalog_reads += 1
        names = ["good"]
        # A fresh clone also exercises an omitted component appearing between
        # planning and adoption, after the first catalog query.
        if catalog_omitted and (previous_baseline or catalog_reads > 1):
            names.append("omitted")
        return [ComponentInfo(app, name, "proc4glsource", "") for name in names]

    monkeypatch.setattr(export, "read_components", catalog)
    if not catalog_omitted:

        def unexpected_projection(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Matching source must not be projected again")

        monkeypatch.setattr(export, "project_component_files", unexpected_projection)
    result = safe_pull.sync_project(connection, load_context(tmp_path))
    assert [failure.component for failure in result.failures] == (
        ["omitted"] if catalog_omitted else []
    )
    assert result.exported == 1
    assert source.exists()
    assert not (folder / "omitted.w4gl").exists()
    saved_names = {
        node.get("name") for node in etree.parse(str(baseline)).findall("COMPONENT")
    }
    assert saved_names == (
        {"good", "omitted"} if previous_baseline and catalog_omitted else {"good"}
    )
    assert (baseline.parent / "omitted.xml").exists() == (
        previous_baseline and catalog_omitted
    )


@pytest.mark.parametrize("race", ["none", "before", "during"])
def test_priming_uses_only_source_bytes_proven_before_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, race: str
) -> None:
    from gorak import comparison_cache, sync_plan
    from gorak.xml_writer import document, new_application, new_component

    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    source = folder / "proc.w4gl"
    source.write_text('[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;')
    xml = document([new_application(folder), new_component(source)])
    snapshot = safe_pull.fingerprint(tmp_path)
    baseline = tmp_path / ".openroad/example/example.xml"
    baseline.parent.mkdir(parents=True)
    changes: dict[Path, bytes | None] = {baseline: xml}
    baseline.write_bytes(xml)
    plan = [
        Change("example", "converged", "added", "added"),
        Change("example/proc", "converged", "added", "added"),
    ]

    def editing() -> None:
        source.write_text(source.read_text().replace("RETURN 1", "RETURN 2"))

    if race == "before":
        editing()
    elif race == "during":
        project_key = comparison_cache.project_key

        def hashing(root: Path) -> str:
            key = project_key(root)
            editing()
            return key

        monkeypatch.setattr(comparison_cache, "project_key", hashing)
    with comparison_cache.scope():
        primed = safe_pull.prime_matching_baseline(tmp_path, snapshot, changes, plan)
        assert primed == (race == "none")
        if race == "none":

            def unexpected_reconstruction(path: Path) -> Any:
                raise AssertionError("Verified baseline adoption already proved source")

            monkeypatch.setattr(
                sync_plan, "comparison_component", unexpected_reconstruction
            )
            current_baseline, _, disk, invalid = sync_plan.local_inventory(tmp_path)
            assert current_baseline == disk
            assert not invalid
        else:
            assert (
                comparison_cache.load(
                    "local:" + str(tmp_path.resolve()),
                    comparison_cache.project_key(tmp_path),
                )
                is None
            )

from itertools import product
from pathlib import Path

import pytest

from gorak import sync_plan
from gorak.connection import OpenRoadConnection
from gorak.domain import Application
from gorak.sync_plan import compare


@pytest.mark.parametrize(
    "baseline,disk,database", list(product([None, "a", "b"], repeat=3))
)
def test_three_way_change_matrix(
    baseline: object, disk: object, database: object
) -> None:
    result = compare("app/component", baseline, disk, database)
    if baseline == disk == database:
        assert result.action == "unchanged"
    elif disk == database:
        assert result.action == "converged"
    elif disk == baseline:
        assert result.action == "pull"
    elif database == baseline:
        assert result.action == "push"
    else:
        assert result.action == "conflict"


def xml(script: str = "RETURN 1;") -> str:
    return f"""<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><APPLICATION name="example"><included_apps><row><appname>core</appname><version>-1</version><imgfilename>core.plb</imgfilename></row><row_class>inclapp</row_class></included_apps></APPLICATION><COMPONENT name="proc" xsi:type="proc4glsource"><script>{script}</script><datatype>integer</datatype></COMPONENT></OPENROAD>"""


def setup(
    root: Path, monkeypatch: pytest.MonkeyPatch, current: str
) -> OpenRoadConnection:
    folder = root / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    (folder / "proc.w4gl").write_text(
        '[proc4glsource]\ndatatype="integer"\n===\nRETURN 1;'
    )
    cached = root / ".openroad/example/example.xml"
    cached.parent.mkdir(parents=True)
    cached.write_text(xml())
    monkeypatch.setattr(
        sync_plan, "read_applications", lambda _: [Application("example", "", "")]
    )
    monkeypatch.setattr(
        sync_plan, "backup_application_xml", lambda c, a, p: p.write_text(current)
    )
    return OpenRoadConnection("local", "node", "db", None)


def test_status_preserves_source_and_detects_conflicting_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = setup(tmp_path, monkeypatch, xml("RETURN 3;"))
    source = tmp_path / "example/proc.w4gl"
    source.write_text(source.read_text().replace("RETURN 1", "RETURN 2"))
    before = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    from gorak.operation_progress import progress_scope

    messages: list[str] = []
    with progress_scope("Status", messages.append):
        changes = sync_plan.plan_project(connection, tmp_path)
    assert any("Comparing local source: 100%" in message for message in messages)
    assert any(
        "Exporting and comparing database applications: 100%" in message
        for message in messages
    )
    assert any("Waiting for native export" in message for message in messages)
    assert next(c for c in changes if c.key == "example/proc").action == "conflict"
    assert before == {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file() and p != tmp_path / ".openroad/comparison-cache.json"
    }


def test_application_deletion_conflicts_with_remote_component_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = setup(tmp_path, monkeypatch, xml("RETURN 3;"))
    (tmp_path / "example/app.json").unlink()
    changes = sync_plan.plan_project(connection, tmp_path)
    app = next(c for c in changes if c.key == "example")
    assert app.action == "conflict"
    assert "component edits" in app.reason


def test_metadata_edit_is_planned_as_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = setup(tmp_path, monkeypatch, xml())
    source = tmp_path / "example/proc.w4gl"
    source.write_text(source.read_text().replace('"integer"', '"varchar"'))
    changes = sync_plan.plan_project(connection, tmp_path)
    item = next(c for c in changes if c.key == "example/proc")
    assert item.action == "push"
    assert item.disk == "modified"


def test_independent_exports_overlap_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Barrier

    from gorak.project import ProjectError

    for name in ["first", "second"]:
        folder = tmp_path / name
        folder.mkdir()
        (folder / "app.json").write_text("{}")
    monkeypatch.setattr(
        sync_plan,
        "read_applications",
        lambda c: [Application(n, "", "") for n in ["first", "second"]],
    )
    barrier = Barrier(2, timeout=5)
    paths: list[Path] = []

    def export(c: OpenRoadConnection, name: str, path: Path) -> None:
        paths.append(path)
        barrier.wait()
        if name == "first":
            raise ProjectError("export failed")
        path.write_text('<OPENROAD><APPLICATION name="second"/></OPENROAD>')

    monkeypatch.setattr(sync_plan, "backup_application_xml", export)
    with pytest.raises(ProjectError, match="export failed"):
        sync_plan.plan_project(
            OpenRoadConnection("local", "node", "db", None), tmp_path
        )
    assert len(paths) == 2
    assert all(not p.parent.exists() for p in paths)


def test_optional_capture_retains_exact_xml_without_altering_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    connection = setup(tmp_path, monkeypatch, xml("RETURN 3;"))
    baseline = (tmp_path / ".openroad/example/example.xml").read_bytes()
    destination = tmp_path / ".openroad/journal-comparisons/test/xml"
    changes = sync_plan.plan_project(connection, tmp_path, capture_dir=destination)
    assert (destination / "0.xml").read_text() == xml("RETURN 3;")
    assert json.loads((destination / "applications.json").read_text()) == {
        "example": "0.xml"
    }
    assert next(c for c in changes if c.key == "example/proc").action == "pull"
    assert (tmp_path / ".openroad/example/example.xml").read_bytes() == baseline


def test_compact_signatures_preserve_xml_comment_and_processing_instruction_content() -> (
    None
):
    from lxml import etree

    def digest(content: str) -> dict[str, str]:
        root = etree.fromstring(
            f'<OPENROAD><COMPONENT name="proc">{content}</COMPONENT></OPENROAD>'
        )
        return sync_plan.semantic_hashes(sync_plan.xml_inventory(root, "example"))

    assert digest("<!--one--><?test value?>") == digest("<!--one--><?test value?>")
    assert digest("<!--one-->") != digest("<!--two-->")
    assert digest("<?test one?>") != digest("<?test two?>")
    assert digest("<!--one-->") != digest("<comment>one</comment>")


def test_inventory_retains_compact_signatures_with_compatible_checkpoint_hashes() -> (
    None
):
    from lxml import etree

    from gorak.native_normalization import signature as native_signature

    root = etree.fromstring(xml().encode())
    component = root.find("COMPONENT")
    assert component is not None
    # Many nested values previously remained expanded in each project inventory.
    for index in range(2000):
        etree.SubElement(component, "property", name=str(index)).text = "value"
    expected = sync_plan.semantic_hashes(
        {"example/proc": native_signature(component, pixel_geometry=True)}
    )["example/proc"]
    inventory = sync_plan.xml_inventory(root, "example")
    digest = inventory["example/proc"]
    assert isinstance(digest, sync_plan.SemanticDigest)
    assert len(digest) == 64
    assert digest == expected
    assert sync_plan.semantic_hashes(inventory)["example/proc"] == expected
    component.find("script").text = "RETURN 2;"
    assert sync_plan.signature(component) != digest


def test_status_cli_keeps_json_on_stdout_and_progress_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    import gorak.cli as cli

    setup(tmp_path, monkeypatch, xml())
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    (tmp_path / ".env").write_text(
        "GORAK_BACKEND=local\nGORAK_SQL_BACKEND=local\n"
        "GORAK_VNODE=node\nGORAK_DATABASE=db\n"
    )
    monkeypatch.chdir(tmp_path)
    from gorak import transfers

    monkeypatch.setattr(transfers, "status", lambda *a: {"push": [], "pull": []})
    cli.main(["status"])
    output = capsys.readouterr()
    assert json.loads(output.out) == {"push": [], "pull": []}
    assert "Status: starting" in output.err


def test_reused_local_comparison_still_exports_database_and_detects_remote_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak.comparison_cache import scope

    connection = setup(tmp_path, monkeypatch, xml())

    calls: list[str] = []

    def exporting(connection: object, app: str, path: Path) -> None:
        calls.append(app)
        path.write_text(xml("RETURN 3;"))

    def reconstructing(path: Path) -> object:
        raise AssertionError("Unchanged local source should reuse its comparison")

    with scope():
        assert all(
            change.action == "unchanged"
            for change in sync_plan.plan_project(connection, tmp_path)
        )
        monkeypatch.setattr(sync_plan, "backup_application_xml", exporting)
        monkeypatch.setattr(sync_plan, "comparison_component", reconstructing)
        changes = sync_plan.plan_project(connection, tmp_path)
    assert calls == ["example"]
    assert (
        next(change for change in changes if change.key == "example/proc").action
        == "pull"
    )

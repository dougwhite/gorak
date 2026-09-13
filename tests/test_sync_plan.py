from itertools import product
from pathlib import Path

import pytest

from gorak import sync_plan
from gorak.connection import OpenRoadConnection
from gorak.domain import Application
from gorak.portable_source import write_companions
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
    write_companions(cached, folder)
    monkeypatch.setattr(
        sync_plan, "read_applications", lambda _: [Application("example", "", "")]
    )
    monkeypatch.setattr(
        sync_plan, "backup_application_xml", lambda c, a, p: p.write_text(current)
    )
    return OpenRoadConnection("local", "node", "db", None)


def test_status_is_read_only_and_detects_conflicting_scripts(
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
    changes = sync_plan.plan_project(connection, tmp_path)
    assert next(c for c in changes if c.key == "example/proc").action == "conflict"
    assert before == {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
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


def test_metadata_edit_reports_conflict_instead_of_disappearing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = setup(tmp_path, monkeypatch, xml())
    source = tmp_path / "example/proc.w4gl"
    source.write_text(source.read_text().replace('"integer"', '"varchar"'))
    changes = sync_plan.plan_project(connection, tmp_path)
    item = next(c for c in changes if c.key == "example/proc")
    assert item.action == "conflict"
    assert item.disk == "invalid"


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

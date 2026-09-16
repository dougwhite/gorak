import json
from pathlib import Path
from typing import Any

import pytest

from gorak import push
from gorak.connection import OpenRoadConnection
from gorak.domain import Application, ComponentInfo
from gorak.importer import signature
from gorak.project import ProjectError
from gorak.xml_writer import document, new_application, new_component


@pytest.fixture(autouse=True)
def mock_compiler(monkeypatch: pytest.MonkeyPatch) -> None:
    from gorak import compiler

    def compile_source(c: Any, a: str, n: str, log: Path) -> compiler.CompileResult:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("Compiled")
        return compiler.CompileResult(True, log)

    monkeypatch.setattr(compiler, "compile_source", compile_source)


def connection() -> OpenRoadConnection:
    return OpenRoadConnection(
        backend="local", vnode="node", database="source", remote_host=None
    )


def app(root: Path, name: str, includes: list[str] | None = None) -> Path:
    folder = root / name
    folder.mkdir()
    (folder / "app.json").write_text(
        json.dumps({"included_applications": includes or []})
    )
    return folder


def test_preflight_rejects_unsupported_before_any_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app(tmp_path, "good")
    folder = app(tmp_path, "bad")
    (folder / "frame.w4gl").write_text("[framesource]\n===\ninitialize()={}")
    monkeypatch.setattr(push, "read_applications", lambda _: [])
    calls: list[Any] = []
    monkeypatch.setattr(push, "import_component_xml", lambda *a, **k: calls.append(a))
    with pytest.raises(ProjectError, match="WML source file"):
        push.push_project(connection(), tmp_path)
    assert not calls


def test_creates_in_dependency_order_and_dry_run_does_not_write_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app(tmp_path, "aaa", ["zzz"])
    app(tmp_path, "zzz")
    monkeypatch.setattr(push, "read_applications", lambda _: [])
    calls: list[str] = []

    def importing(
        conn: Any, name: str, component: str, xml: Path, log: Path, *, create: bool
    ) -> None:
        assert create
        calls.append(name)

    monkeypatch.setattr(push, "import_component_xml", importing)
    monkeypatch.setattr(
        push,
        "backup_application_xml",
        lambda c, a, p: p.write_bytes(document([new_application(tmp_path / a)])),
    )
    assert "2 creations" in push.push_project(connection(), tmp_path, dry_run=True)
    assert calls == []
    push.push_project(connection(), tmp_path)
    assert calls == ["zzz", "aaa"]


def test_database_deletion_is_not_recreated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = app(tmp_path, "example")
    source = folder / "procedure.w4gl"
    source.write_text(
        '[proc4glsource]\ndatatype="integer"\n===\nPROCEDURE procedure() = { RETURN 1; }'
    )
    cache = tmp_path / ".openroad" / "example"
    cache.mkdir(parents=True)
    (cache / "example.xml").write_bytes(
        document([new_application(folder), new_component(source)])
    )
    monkeypatch.setattr(
        push, "read_applications", lambda _: [Application("example", "", "")]
    )
    monkeypatch.setattr(push, "read_components", lambda c, a: [])
    with pytest.raises(ProjectError, match="missing from database"):
        push.push_project(connection(), tmp_path)


def test_collision_requires_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = app(tmp_path, "example")
    (folder / "procedure.w4gl").write_text(
        "[proc4glsource]\n===\nPROCEDURE procedure() = { RETURN; }"
    )
    monkeypatch.setattr(
        push, "read_applications", lambda _: [Application("example", "", "")]
    )
    monkeypatch.setattr(
        push,
        "read_components",
        lambda c, a: [ComponentInfo("example", "procedure", "proc4glsource", "")],
    )
    with pytest.raises(ProjectError, match="baseline"):
        push.push_project(connection(), tmp_path)


def test_missing_include_rejected_before_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app(tmp_path, "example", ["missing"])
    monkeypatch.setattr(push, "read_applications", lambda _: [])
    with pytest.raises(ProjectError, match="missing or cyclic"):
        push.push_project(connection(), tmp_path)


def test_failed_creation_does_not_advance_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app(tmp_path, "example")
    monkeypatch.setattr(push, "read_applications", lambda _: [])

    def fail(*args: Any, **kwargs: Any) -> None:
        raise ProjectError("compilation failed")

    monkeypatch.setattr(push, "import_component_xml", fail)
    with pytest.raises(ProjectError, match="earlier operations may have succeeded"):
        push.push_project(connection(), tmp_path)
    assert not (tmp_path / ".openroad" / "example").exists()
    assert not (tmp_path / ".openroad" / "pushes" / "push.lock").exists()
    assert list((tmp_path / ".openroad" / "pushes").glob("*/0-submitted.xml"))


def test_metadata_update_preserves_existing_components_and_includes_new_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lxml import etree

    folder = app(tmp_path, "example")
    source = folder / "existing.w4gl"
    source.write_text("[proc4glsource]\n===\nPROCEDURE existing() = { RETURN; }")
    baseline = document([new_application(folder), new_component(source)])
    cache = tmp_path / ".openroad" / "example"
    cache.mkdir(parents=True)
    (cache / "example.xml").write_bytes(baseline)
    (folder / "app.json").write_text(
        json.dumps(
            {"starting_component": "runtests", "included_applications": ["framework"]}
        )
    )
    (folder / "runtests.w4gl").write_text(
        "[proc4glsource]\n===\nPROCEDURE runtests() = { RETURN; }"
    )
    monkeypatch.setattr(
        push,
        "read_applications",
        lambda _: [Application("example", "", ""), Application("framework", "", "")],
    )
    monkeypatch.setattr(
        push,
        "read_components",
        lambda c, a: [ComponentInfo("example", "existing", "proc4glsource", "")],
    )
    database = [baseline]
    monkeypatch.setattr(
        push, "backup_application_xml", lambda c, a, p: p.write_bytes(database[0])
    )

    def importing(
        c: Any, a: str, component: str, xml: Path, log: Path, *, create: bool
    ) -> None:
        assert not create
        assert component == "-"
        database[0] = xml.read_bytes()

    monkeypatch.setattr(push, "import_component_xml", importing)
    result = push.push_project(connection(), tmp_path)
    assert "1 application updates" in result
    tree = etree.fromstring(database[0])
    assert tree.findtext("APPLICATION/procstart") == "runtests"
    assert [n.get("name") for n in tree.findall("COMPONENT")] == [
        "existing",
        "runtests",
    ]
    assert (cache / "example.xml").read_bytes() == database[0]


def test_metadata_conflict_aborts_before_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = app(tmp_path, "example")
    cache = tmp_path / ".openroad" / "example"
    cache.mkdir(parents=True)
    (cache / "example.xml").write_bytes(document([new_application(folder)]))
    (folder / "app.json").write_text('{"description":"disk edit"}')
    monkeypatch.setattr(
        push, "read_applications", lambda _: [Application("example", "", "")]
    )
    monkeypatch.setattr(
        push,
        "backup_application_xml",
        lambda c, a, p: p.write_text(
            '<OPENROAD><APPLICATION name="example"><versshortremarks>workbench edit</versshortremarks></APPLICATION></OPENROAD>'
        ),
    )
    with pytest.raises(ProjectError, match="metadata changed since export"):
        push.push_project(connection(), tmp_path)


def test_fresh_push_restores_exported_frame_without_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lxml import etree

    from gorak.readable_source import encode_component

    folder = app(tmp_path, "example")
    node = etree.parse("tests/fixtures/fm_example_frame.xml").find("COMPONENT")
    assert node is not None
    source = folder / f"{node.get('name')}.w4gl"
    text, markup = encode_component(node)
    source.write_text(text)
    source.with_suffix(".wml").write_text(markup or "")
    assert not list(tmp_path.rglob("*.xml"))
    assert not (tmp_path / ".openroad").exists()
    monkeypatch.setattr(push, "read_applications", lambda _: [])
    imported: list[bytes] = []

    def importing(
        c: Any, a: str, comp: str, path: Path, log: Path, *, create: bool
    ) -> None:
        assert create and comp == "-"
        imported.append(path.read_bytes())

    monkeypatch.setattr(push, "import_component_xml", importing)
    monkeypatch.setattr(
        push, "backup_application_xml", lambda c, a, p: p.write_bytes(imported[0])
    )
    assert "1 creations" in push.push_project(connection(), tmp_path)
    restored = etree.fromstring(imported[0]).find("COMPONENT")
    assert restored is not None
    assert signature(restored) == signature(node)


def test_new_disk_file_during_preflight_prevents_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = app(tmp_path, "example")

    def inventory(c: Any) -> list[Application]:
        (folder / "late.w4gl").write_text("[proc4glsource]\n===\nPROCEDURE late() = {}")
        return []

    monkeypatch.setattr(push, "read_applications", inventory)
    monkeypatch.setattr(
        push,
        "import_component_xml",
        lambda *a, **k: pytest.fail("Imported changed project"),
    )
    with pytest.raises(ProjectError, match="Local project changed"):
        push.push_project(connection(), tmp_path)
    assert not (tmp_path / ".openroad/push-pending.json").exists()


def test_application_appearing_after_preflight_prevents_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app(tmp_path, "example")
    inventories = iter([[], [Application("example", "", "")]])
    monkeypatch.setattr(push, "read_applications", lambda c: next(inventories))
    monkeypatch.setattr(
        push,
        "import_component_xml",
        lambda *a, **k: pytest.fail("Overwrote new database application"),
    )
    with pytest.raises(ProjectError, match="Application appeared"):
        push.push_project(connection(), tmp_path)


def test_late_disk_edit_keeps_cache_unadvanced_and_blocks_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = app(tmp_path, "example")
    original = document([new_application(folder)])
    monkeypatch.setattr(push, "read_applications", lambda c: [])

    def importing(*args: Any, **kwargs: Any) -> None:
        (folder / "notes.txt").write_text("concurrent edit")

    monkeypatch.setattr(push, "import_component_xml", importing)
    monkeypatch.setattr(
        push, "backup_application_xml", lambda c, a, p: p.write_bytes(original)
    )
    with pytest.raises(ProjectError, match="Local project changed"):
        push.push_project(connection(), tmp_path)
    assert not (tmp_path / ".openroad/example/example.xml").exists()
    marker = tmp_path / ".openroad/push-pending.json"
    operation = Path(json.loads(marker.read_text())["operation"])
    assert (operation / "plan.json").exists()
    assert (operation / "0-after.xml").exists()
    with pytest.raises(ProjectError, match="interrupted push"):
        push.push_project(connection(), tmp_path)
    assert (folder / "notes.txt").read_text() == "concurrent edit"


@pytest.mark.parametrize("unexpected_change", [False, True])
@pytest.mark.parametrize("complete", [False, True])
def test_app_metadata_and_frame_geometry_share_verified_canonicalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unexpected_change: bool,
    complete: bool,
) -> None:
    from lxml import etree

    from gorak import importer
    from gorak.parser import encode_w4gl, encode_wml, parse_component_node

    folder = app(tmp_path, "example")
    node = etree.fromstring(
        b'<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="panel" xsi:type="framesource"><script>initialize()={}</script><topform><width>1000</width><childfields><row xsi:type="entryfield"><name>input</name><xleft>104</xleft></row><row_class>formfield</row_class></childfields></topform></COMPONENT>'
    )
    from gorak.readable_source import encode_application, encode_component

    component = parse_component_node(node)
    source = folder / "panel.w4gl"
    text, wml = (
        encode_component(node)
        if complete
        else (encode_w4gl(component), encode_wml(component))
    )
    source.write_text(text)
    markup = source.with_suffix(".wml")
    markup.write_text((wml or "").replace('xleft="104"', 'xleft="321"'))
    app_node = new_application(folder)
    baseline = document([app_node, node])
    cache = tmp_path / ".openroad/example/example.xml"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(baseline)
    app_values = encode_application(app_node) if complete else {}
    app_values["description"] = "Updated description"
    (folder / "app.json").write_text(json.dumps(app_values))
    monkeypatch.setattr(
        push, "read_applications", lambda _: [Application("example", "", "")]
    )
    monkeypatch.setattr(
        push,
        "read_components",
        lambda c, a: [ComponentInfo("example", "panel", "framesource", "")],
    )
    database = [baseline]
    monkeypatch.setattr(
        push, "backup_application_xml", lambda c, a, p: p.write_bytes(database[0])
    )
    monkeypatch.setattr(
        importer, "backup_component_xml", lambda c, a, n, p: p.write_bytes(database[0])
    )
    imports = []

    def importing(
        c: Any, a: str, name: str, xml: Path, log: Path, *, create: bool
    ) -> None:
        assert name == "-" and not create
        imports.append(xml.read_bytes())
        database[0] = imports[-1].replace(b"<xleft>321</xleft>", b"<xleft>323</xleft>")
        if unexpected_change:
            database[0] = database[0].replace(
                b"initialize()={}", b"initialize()={ MESSAGE 'unexpected'; }"
            )

    monkeypatch.setattr(push, "import_component_xml", importing)
    if unexpected_change:
        with pytest.raises(ProjectError, match="Existing component changed"):
            push.push_project(connection(), tmp_path)
        assert cache.read_bytes() == baseline
        assert 'xleft="321"' in markup.read_text()
        assert (tmp_path / ".openroad/push-pending.json").exists()
    else:
        assert "1 application updates" in push.push_project(connection(), tmp_path)
        assert cache.read_bytes() == database[0]
        assert 'xleft="323"' in markup.read_text()
        assert not (tmp_path / ".openroad/push-pending.json").exists()
        assert "no changes" in push.push_project(connection(), tmp_path)
    assert len(imports) == 1

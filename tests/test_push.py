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
    with pytest.raises(ProjectError, match="not supported"):
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

    from gorak.export import apply_field_default_inheritance
    from gorak.parser import encode_w4gl, encode_wml, parse_component_node
    from gorak.portable_source import write_companions

    folder = app(tmp_path, "example")
    xml = Path("tests/fixtures/fm_example_frame.xml")
    node = etree.parse(str(xml)).find("COMPONENT")
    assert node is not None
    component = parse_component_node(node)
    apply_field_default_inheritance(tmp_path, "example", [component])
    source = folder / f"{component.name}.w4gl"
    source.write_text(encode_w4gl(component))
    source.with_suffix(".wml").write_text(encode_wml(component) or "")
    write_companions(xml, folder)
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

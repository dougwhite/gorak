from pathlib import Path

import pytest
from lxml import etree
from pytest import MonkeyPatch

from gorak import importer
from gorak.connection import OpenRoadConnection
from gorak.parser import encode_w4gl, parse_xml
from gorak.project import ProjectError

XML = b"""<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><COMPONENT name="example" xsi:type="proc4glsource"><script><![CDATA[PROCEDURE example() = { RETURN 0; }]]></script><datatype>integer</datatype><extension><opaque value="keep"/></extension></COMPONENT></OPENROAD>"""
CONNECTION = OpenRoadConnection("local", "node", "demo", None)


def project(root: Path) -> Path:
    (root / "app").mkdir()
    cache = root / ".openroad" / "app"
    cache.mkdir(parents=True)
    (cache / "example.xml").write_bytes(XML)
    source = root / "app" / "example.w4gl"
    source.write_text(
        encode_w4gl(parse_xml(etree.fromstring(XML))).replace("RETURN 0", "RETURN 1")
    )
    return source


@pytest.mark.parametrize("advance_cache", [False, True])
def test_import_preserves_opaque_xml_and_verifies(
    tmp_path: Path, monkeypatch: MonkeyPatch, advance_cache: bool
) -> None:
    source = project(tmp_path)
    uploaded: list[bytes] = []

    def export(
        connection: OpenRoadConnection, app: str, component: str, path: Path
    ) -> None:
        path.write_bytes(uploaded[-1] if uploaded else XML)

    def push(
        connection: OpenRoadConnection, app: str, component: str, path: Path, log: Path
    ) -> None:
        uploaded.append(path.read_bytes())
        log.write_text("compiled")

    monkeypatch.setattr(importer, "backup_component_xml", export)
    monkeypatch.setattr(importer, "import_component_xml", push)
    result = importer.import_component(
        CONNECTION, tmp_path, "app", "example", advance_cache=advance_cache
    )
    assert b"RETURN 1" in uploaded[0]
    assert b'<opaque value="keep"/>' in uploaded[0]
    assert (result / "before.xml").read_bytes() == XML
    assert (tmp_path / ".openroad/app/example.xml").read_bytes() == (
        uploaded[0] if advance_cache else XML
    )
    assert (result / "after.xml").read_bytes() == uploaded[0]
    assert "RETURN 1" in source.read_text()


@pytest.mark.parametrize("change", ["metadata", "database", "missing", "frame"])
def test_rejects_unsafe_import_before_write(
    tmp_path: Path, monkeypatch: MonkeyPatch, change: str
) -> None:
    source = project(tmp_path)
    current = XML
    if change == "metadata":
        source.write_text(
            source.read_text().replace('datatype = "integer"', 'datatype = "varchar"')
        )
    if change == "database":
        current = XML.replace(b"RETURN 0", b"RETURN 2")
    if change == "missing":
        (tmp_path / ".openroad/app/example.xml").unlink()
    if change == "frame":
        (tmp_path / ".openroad/app/example.xml").write_bytes(
            XML.replace(b"proc4glsource", b"framesource")
        )

    def export(
        connection: OpenRoadConnection, app: str, component: str, path: Path
    ) -> None:
        path.write_bytes(current)

    monkeypatch.setattr(importer, "backup_component_xml", export)
    monkeypatch.setattr(
        importer, "import_component_xml", lambda *a: pytest.fail("must not import")
    )
    with pytest.raises(ProjectError):
        importer.import_component(CONNECTION, tmp_path, "app", "example")
    assert "RETURN 1" in source.read_text()


def test_verification_failure_preserves_baseline(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    project(tmp_path)

    def export(
        connection: OpenRoadConnection, app: str, component: str, path: Path
    ) -> None:
        path.write_bytes(XML)

    monkeypatch.setattr(importer, "backup_component_xml", export)
    monkeypatch.setattr(importer, "import_component_xml", lambda *a: None)
    with pytest.raises(ProjectError, match="verification"):
        importer.import_component(CONNECTION, tmp_path, "app", "example")
    assert (tmp_path / ".openroad/app/example.xml").read_bytes() == XML
    assert list((tmp_path / ".openroad/imports").glob("*/submitted.xml"))


def test_dry_run_prepares_xml_without_import_or_cache_update(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    project(tmp_path)

    def export(
        connection: OpenRoadConnection, app: str, component: str, path: Path
    ) -> None:
        path.write_bytes(XML)

    monkeypatch.setattr(importer, "backup_component_xml", export)
    monkeypatch.setattr(
        importer,
        "import_component_xml",
        lambda *a: pytest.fail("dry run wrote database"),
    )
    result = importer.import_component(
        CONNECTION, tmp_path, "app", "example", dry_run=True
    )
    assert b"RETURN 1" in (result / "submitted.xml").read_bytes()
    assert (tmp_path / ".openroad/app/example.xml").read_bytes() == XML


def test_rejects_unrecognized_front_matter(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = project(tmp_path)
    source.write_text('unsupported = "value"\n' + source.read_text())
    monkeypatch.setattr(
        importer, "backup_component_xml", lambda *a: pytest.fail("must validate first")
    )
    with pytest.raises(ProjectError, match="Metadata"):
        importer.import_component(CONNECTION, tmp_path, "app", "example")


def test_application_export_baseline_and_class_script(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = project(tmp_path)
    cache = tmp_path / ".openroad/app"
    (cache / "example.xml").unlink()
    xml = XML.replace(b"proc4glsource", b"classsource")
    (cache / "app.xml").write_bytes(xml)
    source.write_text(source.read_text().replace("proc4glsource", "classsource"))

    def export(
        connection: OpenRoadConnection, app: str, component: str, path: Path
    ) -> None:
        path.write_bytes(xml)

    monkeypatch.setattr(importer, "backup_component_xml", export)
    result = importer.import_component(
        CONNECTION, tmp_path, "app", "example", dry_run=True
    )
    assert b"classsource" in (result / "submitted.xml").read_bytes()


def test_failed_import_retains_source_and_baseline(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = project(tmp_path)

    def export(
        connection: OpenRoadConnection, app: str, component: str, path: Path
    ) -> None:
        path.write_bytes(XML)

    def fail(*args: object) -> None:
        raise ProjectError("compilation failed")

    monkeypatch.setattr(importer, "backup_component_xml", export)
    monkeypatch.setattr(importer, "import_component_xml", fail)
    with pytest.raises(ProjectError, match="database may have changed"):
        importer.import_component(CONNECTION, tmp_path, "app", "example")
    assert "RETURN 1" in source.read_text()
    assert (tmp_path / ".openroad/app/example.xml").read_bytes() == XML
    assert not (tmp_path / ".openroad/imports/import.lock").exists()


def test_detects_changes_to_unrepresented_database_metadata(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    project(tmp_path)

    def export(
        connection: OpenRoadConnection, app: str, component: str, path: Path
    ) -> None:
        path.write_bytes(XML.replace(b'value="keep"', b'value="changed"'))

    monkeypatch.setattr(importer, "backup_component_xml", export)
    monkeypatch.setattr(
        importer,
        "import_component_xml",
        lambda *a: pytest.fail("must not overwrite metadata"),
    )
    with pytest.raises(ProjectError, match="changed since export"):
        importer.import_component(CONNECTION, tmp_path, "app", "example")


def test_source_save_during_preparation_aborts(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    source = project(tmp_path)

    def export(
        connection: OpenRoadConnection, app: str, component: str, path: Path
    ) -> None:
        path.write_bytes(XML)
        source.write_text(source.read_text().replace("RETURN 1", "RETURN 3"))

    monkeypatch.setattr(importer, "backup_component_xml", export)
    monkeypatch.setattr(
        importer,
        "import_component_xml",
        lambda *a: pytest.fail("must not write stale source"),
    )
    with pytest.raises(ProjectError, match="Local source changed"):
        importer.import_component(CONNECTION, tmp_path, "app", "example")
    assert "RETURN 3" in source.read_text()


def test_existing_import_lock_is_preserved(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    project(tmp_path)
    operations = tmp_path / ".openroad/imports"
    operations.mkdir()
    lock = operations / "import.lock"
    lock.write_text("another operation")
    monkeypatch.setattr(
        importer,
        "backup_component_xml",
        lambda *a: pytest.fail("must not run concurrently"),
    )
    with pytest.raises(ProjectError, match="Another import"):
        importer.import_component(CONNECTION, tmp_path, "app", "example")
    assert lock.read_text() == "another operation"

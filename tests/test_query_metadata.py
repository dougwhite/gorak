"""Saved query sidecars preserve source and participate in synchronization."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from lxml import etree

from gorak.contract_source import decode_component, equivalent
from gorak.errors import ProjectError
from gorak.importer import signature
from gorak.parser import NS, parse_component_node
from gorak.portable_source import comparison_component, overlay_component
from gorak.query_metadata import encode_queries, query_path, read_queries, write_queries
from gorak.safe_pull import apply_files, fingerprint
from gorak.sync_plan import compare
from tests.native_source import write_component


def component(kind: str = "classsource") -> etree._Element:
    node = etree.fromstring(f'''<COMPONENT xmlns:xsi="{NS["xsi"]}" name="sample" xsi:type="{kind}">
<script>initialize()={{}}</script><queries>
<row><name>main</name><columns><row><columnname>code</columnname><targets>
<row><expression>this.code</expression><isinserttarget>1</isinserttarget><isselecttarget>1</isselecttarget><isupdatetarget>0</isupdatetarget></row>
<row><expression>that.code</expression><isdeletewhere>1</isdeletewhere><isupdatewhere>1</isupdatewhere></row><row_class>queryparm</row_class>
</targets></row><row_class>querycol</row_class></columns><targetprefix>this.</targetprefix>
<tables><row><tablename>items</tablename><corrname>i</corrname></row><row><tablename>groups</tablename><corrname>g</corrname></row><row_class>querytable</row_class></tables><designtimewhere>i.group_id = g.id</designtimewhere></row>
<row xsi:type="queryobject"><name>lookup</name><designtimewhere/><targetprefix/></row><row_class>queryobject</row_class>
</queries></COMPONENT>''')
    if kind == "framesource":
        etree.SubElement(node, "topform")
        etree.SubElement(node, "fielddefaults")
    return node


def source(root: Path, node: etree._Element) -> Path:
    folder = root / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    path = folder / "sample.w4gl"
    write_component(path, node)
    cache = root / ".openroad/example"
    cache.mkdir(parents=True)
    document = etree.Element("OPENROAD")
    document.append(deepcopy(node))
    (cache / "sample.xml").write_bytes(etree.tostring(document))
    return path


@pytest.mark.parametrize("kind", ["classsource", "framesource"])
def test_roundtrip_queries_and_missing_sidecar_protection(
    tmp_path: Path, kind: str
) -> None:
    original = component(kind)
    path = source(tmp_path, original)
    assert equivalent(original, decode_component(path))
    assert signature(original.find("queries")) == signature(read_queries(path))
    assert '"queries"' not in path.read_text()
    query_path(path).unlink()
    with pytest.raises(ProjectError, match="Missing query metadata"):
        comparison_component(path)
    query_path(path).write_text('{"version": 1, "queries": null}')
    assert overlay_component(deepcopy(original), path).find("queries") is None
    assert decode_component(path).find("queries") is None


def test_sidecar_edits_participate_in_three_way_comparison(tmp_path: Path) -> None:
    original = component()
    path = source(tmp_path, original)
    before = fingerprint(tmp_path)
    data = json.loads(query_path(path).read_text())
    data["queries"]["row"]["row1"]["name"] = "edited"
    query_path(path).write_text(json.dumps(data))
    assert before != fingerprint(tmp_path)
    local = signature(comparison_component(path))
    baseline = signature(original)
    assert compare("example/sample", baseline, local, baseline).action == "push"
    from gorak.connection import OpenRoadConnection
    from gorak.sync_plan import baseline_inventory, plan_project, semantic_hashes

    changes = plan_project(
        OpenRoadConnection("local", "node", "db", None),
        tmp_path,
        database_hashes=semantic_hashes(baseline_inventory(tmp_path)[0]),
    )
    assert (
        next(change for change in changes if change.key == "example/sample").action
        == "push"
    )
    remote = deepcopy(original)
    remote.find("queries/row/name").text = "remote"
    assert (
        compare("example/sample", baseline, local, signature(remote)).action
        == "conflict"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '{"version":2,"queries":{}}',
        '{"version":true,"queries":{}}',
        '{"version":1,"queries":{},"queries":null}',
        '{"version":1,"queries":{"row":{"row2":{}}}}',
    ],
)
def test_invalid_metadata_is_refused(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "sample.w4gl"
    query_path(path).write_text(raw)
    with pytest.raises(ProjectError):
        read_queries(path)


def test_empty_absent_and_control_characters(tmp_path: Path) -> None:
    path = tmp_path / "sample.w4gl"
    node = etree.fromstring(
        "<COMPONENT><queries><row><expression>a<?ingres_invalidxmlchar 7?>b</expression></row><row_class>queryobject</row_class></queries></COMPONENT>"
    )
    write_queries(path, encode_queries(node))
    assert signature(read_queries(path)) == signature(node.find("queries"))
    empty = etree.fromstring("<COMPONENT><queries/></COMPONENT>")
    write_queries(path, encode_queries(empty))
    assert read_queries(path) is not None
    write_queries(path, None)
    assert not query_path(path).exists()
    assert parse_component_node(component()).queries is not None


def test_query_sidecar_rollback_retains_before_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = source(tmp_path, component())
    sidecar = query_path(path)
    old = sidecar.read_bytes()
    recovery = tmp_path / ".openroad/recovery"
    recovery.mkdir()
    original_replace = Path.replace

    def replace(current: Path, target: Path) -> Path:
        if target == path:
            raise OSError("injected write failure")
        return original_replace(current, target)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(OSError):
        apply_files(
            tmp_path,
            {sidecar: b'{"version":1,"queries":null}', path: b"changed"},
            recovery,
        )
    assert sidecar.read_bytes() == old
    assert (recovery / "before/example/sample.queries.json").read_bytes() == old


def test_component_export_writes_and_removes_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import export
    from gorak.connection import OpenRoadConnection

    node = component()
    document = etree.Element("OPENROAD")
    document.append(node)

    def backup(connection: object, app: str, name: str, output: Path) -> None:
        output.write_bytes(etree.tostring(document))

    monkeypatch.setattr(export, "backup_component_xml", backup)
    paths = export.component_export_paths(tmp_path, "example", "sample")
    connection = OpenRoadConnection("local", "node", "db", None)
    path = export.export_component_to_paths(connection, "example", "sample", paths)
    assert signature(read_queries(path)) == signature(node.find("queries"))
    node.remove(node.find("queries"))
    export.export_component_to_paths(connection, "example", "sample", paths)
    assert not query_path(path).exists()


def test_failed_import_keeps_queries_in_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import importer
    from gorak.connection import OpenRoadConnection

    node = component()
    path = source(tmp_path, node)
    saved = query_path(path).read_bytes()
    document = etree.Element("OPENROAD")
    document.append(node)

    def backup(connection: object, app: str, name: str, output: Path) -> None:
        output.write_bytes(etree.tostring(document))

    def fail(*args: object) -> None:
        raise ProjectError("injected import failure")

    monkeypatch.setattr(importer, "backup_component_xml", backup)
    monkeypatch.setattr(importer, "import_component_xml", fail)
    with pytest.raises(ProjectError, match="injected import failure"):
        importer.import_component(
            OpenRoadConnection("local", "node", "db", None),
            tmp_path,
            "example",
            "sample",
        )
    assert query_path(path).read_bytes() == saved
    copies = list((tmp_path / ".openroad/imports").glob("*/source.queries.json"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == saved


@pytest.mark.parametrize(
    "xml",
    [
        "<COMPONENT><queries/><queries/></COMPONENT>",
        "<COMPONENT><queries><name>a</name><name>b</name></queries></COMPONENT>",
        "<COMPONENT><queries>mixed<row/></queries></COMPONENT>",
    ],
)
def test_unrepresentable_query_structure_is_refused(xml: str) -> None:
    with pytest.raises(ProjectError):
        encode_queries(etree.fromstring(xml))

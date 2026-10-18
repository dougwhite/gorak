"""Native-accepted populated frmflow must survive source edits and verification.

Fixture provenance: https://github.com/dougwhite/gorak/issues/61#issuecomment-6243090159
The synthetic XML was imported and freshly exported by native OpenROAD. Query
execution and reopening the contrived graph in a template wizard were not tested.
"""

import json
import tomllib
from copy import deepcopy
from pathlib import Path

import pytest
from lxml import etree

from gorak.contract_source import equivalent
from gorak.errors import ProjectError
from gorak.frame_flow import encode_flow, flow_path, flow_signature, read_flow
from gorak.native_normalization import signature as native_signature
from gorak.parser import parse_component_node
from gorak.portable_source import overlay_component, restore_component
from tests.native_source import write_component


def native() -> etree._Element:
    root = etree.parse(str(Path(__file__).parent / "fixtures/frmflow-61.xml"))
    node = root.find("COMPONENT")
    assert node is not None
    return node


def source(tmp_path: Path, node: etree._Element) -> Path:
    path = tmp_path / "frmflow_regression.w4gl"
    write_component(path, node)
    return path


def test_native_fixture_cold_noop_and_unrelated_edit(tmp_path: Path) -> None:
    original = native()
    path = source(tmp_path, original)
    assert parse_component_node(original).frmflow is not None
    cold = restore_component(path)
    assert flow_signature(cold) == flow_signature(original)
    assert equivalent(cold, original)
    assert flow_path(path).is_file()
    assert (
        "frmflow" not in tomllib.loads(path.read_text().split("===")[0])["framesource"]
    )
    # Match only native defaults in the surrounding frame to exercise no-op.
    baseline = deepcopy(cold)
    baseline.replace(baseline.find("frmflow"), deepcopy(original.find("frmflow")))
    assert overlay_component(baseline, path) is baseline
    assert flow_signature(baseline) == flow_signature(original)
    path.write_text(
        path.read_text().replace("Synthetic structured", "Edited structured")
    )
    edited = overlay_component(deepcopy(original), path)
    assert edited.findtext("versshortremarks").startswith("Edited")
    assert flow_signature(edited) == flow_signature(original)


@pytest.mark.parametrize(
    "mutation", ["remove", "expression", "reference", "order", "type", "empty_scalar"]
)
def test_independent_verification_detects_loss_and_changes(mutation: str) -> None:
    original = native()
    changed = deepcopy(original)
    flow = changed.find("frmflow")
    if mutation == "remove":
        changed.remove(flow)
    elif mutation == "expression":
        flow.find("query/rescols/row/expression").text = "wrong"
    elif mutation == "reference":
        flow.find("query/rescols/row/tblcol").set("oidref", "3")
    elif mutation == "order":
        rows = flow.find("query/rescols")
        rows.insert(0, rows[1])
    elif mutation == "type":
        flow.find("query/rescols/row_class").text = "other"
    else:
        etree.SubElement(flow, "defaultstring")
    assert not equivalent(original, changed)
    assert native_signature(original) != native_signature(changed)


def test_consistent_id_renumbering_and_shared_references() -> None:
    original = native()
    renumbered = deepcopy(original)
    for node in renumbered.find("frmflow").iter():
        for key in ("oid", "oidref"):
            if node.get(key) is not None:
                node.set(key, str(int(node.get(key)) + 100))
    assert equivalent(original, renumbered)
    assert native_signature(original) == native_signature(renumbered)
    # The comparison is independent of readable projection.
    from unittest.mock import patch

    import gorak.frame_flow as module

    with patch.object(module, "encode_flow", return_value=None):
        missing = deepcopy(original)
        missing.remove(missing.find("frmflow"))
        assert not equivalent(original, missing)


@pytest.mark.parametrize(
    "xml",
    [
        "<frmflow/>",
        "<frmflow><row_class>menufield</row_class></frmflow>",
        "<frmflow>literal scalar</frmflow>",
        "<frmflow> a&#13;\n<?ingres_invalidxmlchar 7?>b </frmflow>",
    ],
)
def test_empty_typed_empty_scalar_and_character_controls(
    tmp_path: Path, xml: str
) -> None:
    original = native()
    original.replace(original.find("frmflow"), etree.fromstring(xml))
    path = source(tmp_path, original)
    assert equivalent(original, restore_component(path))
    assert flow_signature(original) == flow_signature(restore_component(path))
    missing = deepcopy(original)
    missing.remove(missing.find("frmflow"))
    assert not equivalent(original, missing)


def test_missing_sidecar_requires_explicit_removal(tmp_path: Path) -> None:
    original = native()
    path = source(tmp_path, original)
    flow_path(path).unlink()
    with pytest.raises(ProjectError, match="Missing frmflow metadata"):
        overlay_component(deepcopy(original), path)
    flow_path(path).write_text('{"version":1,"frmflow":null}')
    assert overlay_component(deepcopy(original), path).find("frmflow") is None
    assert restore_component(path).find("frmflow") is None


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '{"version":true,"frmflow":null}',
        '{"version":2,"frmflow":null}',
        '{"version":1,"frmflow":null,"frmflow":null}',
        '{"version":1,"frmflow":{"tag":"wrong","text":""}}',
        '{"version":1,"frmflow":{"tag":"frmflow","text":1}}',
        '{"version":1,"frmflow":{"tag":"frmflow","text":"","children":[]}}',
        '{"version":1,"frmflow":{"tag":"frmflow","children":[]}}',
        '{"version":1,"frmflow":{"tag":"frmflow","attributes":{"oidref":"missing"},"text":""}}',
    ],
)
def test_invalid_sidecars_refused(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "sample.w4gl"
    flow_path(path).write_text(raw)
    with pytest.raises(ProjectError, match="Invalid frmflow metadata"):
        read_flow(path)


@pytest.mark.parametrize(
    "xml",
    [
        '<frmflow><item oid="1"/><item oid="1"/></frmflow>',
        '<frmflow><item oidref="missing"/></frmflow>',
        "<frmflow>lost<item/></frmflow>",
        "<frmflow><item/>lost</frmflow>",
    ],
)
def test_unsupported_native_graph_refused(xml: str) -> None:
    original = native()
    original.replace(original.find("frmflow"), etree.fromstring(xml))
    with pytest.raises(ProjectError):
        parse_component_node(original)


def test_projection_export_is_atomic_and_removes_obsolete_sidecar(
    tmp_path: Path,
) -> None:
    from gorak.export import project_component_files
    from gorak.export_failures import ComponentProjectionError
    from gorak.image_assets import AssetWriter

    original = native()
    writer = AssetWriter(tmp_path)
    component = project_component_files(original, tmp_path, writer, None)
    path = tmp_path / f"{component.name}.w4gl"
    assert flow_signature(restore_component(path)) == flow_signature(original)
    before = {p: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    invalid = deepcopy(original)
    invalid.find("frmflow/query/rescols/row/tblcol").set("oidref", "missing")
    with pytest.raises(ComponentProjectionError):
        project_component_files(invalid, tmp_path, writer, None)
    assert all(p.read_bytes() == value for p, value in before.items())
    original.remove(original.find("frmflow"))
    project_component_files(original, tmp_path, writer, None)
    assert not flow_path(path).exists()


def test_sidecar_edit_changes_fingerprint_and_semantic_state(tmp_path: Path) -> None:
    from gorak.safe_pull import fingerprint

    original = native()
    path = source(tmp_path, original)
    before = fingerprint(tmp_path)
    value = encode_flow(original)
    assert value is not None
    value["frmflow"]["children"][-1]["text"] = "2"
    flow_path(path).write_text(json.dumps(value))
    assert before != fingerprint(tmp_path)
    assert not equivalent(original, restore_component(path))


def test_sidecar_edits_participate_in_sync_planning(tmp_path: Path) -> None:
    from gorak.connection import OpenRoadConnection
    from gorak.sync_plan import baseline_inventory, plan_project, semantic_hashes

    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    original = native()
    path = source(folder, original)
    cache = tmp_path / ".openroad/example"
    cache.mkdir(parents=True)
    document = etree.Element("OPENROAD")
    document.append(original)
    (cache / "sample.xml").write_bytes(etree.tostring(document))
    baseline = semantic_hashes(baseline_inventory(tmp_path)[0])
    value = encode_flow(original)
    assert value is not None
    value["frmflow"]["children"][-1]["text"] = "2"
    flow_path(path).write_text(json.dumps(value))
    changes = plan_project(
        OpenRoadConnection("local", "node", "db", None),
        tmp_path,
        database_hashes=baseline,
    )
    assert (
        next(c for c in changes if c.key.endswith("/frmflow_regression")).action
        == "push"
    )


def test_failed_import_retains_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import importer
    from gorak.connection import OpenRoadConnection

    folder = tmp_path / "example"
    folder.mkdir()
    original = native()
    path = source(folder, original)
    saved = flow_path(path).read_bytes()
    document = etree.Element("OPENROAD")
    document.append(original)
    cache = tmp_path / ".openroad/example"
    cache.mkdir(parents=True)
    (cache / "frmflow_regression.xml").write_bytes(etree.tostring(document))

    def backup(connection: object, app: str, name: str, output: Path) -> None:
        output.write_bytes(etree.tostring(document))

    def fail(*args: object) -> None:
        raise ProjectError("injected failure")

    monkeypatch.setattr(importer, "backup_component_xml", backup)
    monkeypatch.setattr(importer, "import_component_xml", fail)
    with pytest.raises(ProjectError, match="injected failure"):
        importer.import_component(
            OpenRoadConnection("local", "node", "db", None),
            tmp_path,
            "example",
            "frmflow_regression",
        )
    copies = list((tmp_path / ".openroad/imports").glob("*/source.frmflow.json"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == saved == flow_path(path).read_bytes()

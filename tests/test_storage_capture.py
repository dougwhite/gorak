from pathlib import Path

import pytest

from gorak.encoded_graph import UnsupportedSource
from gorak.storage_capture import capture
from tests.test_storage_archive import archive
from tests.test_storage_restore import SETTINGS, Backend


def test_capture_resolves_case_variant_base_names_and_normalizes_ids(
    tmp_path: Path,
) -> None:
    backend = Backend(tmp_path / "source.sqlite")
    source = archive().remap({1: 51, 2: 52, 3: 53, 4: 54})
    source.tables["ii_entities"][0]["entity_name"] = "SAMPLE"
    backend.seed(source)
    result, stale = capture(SETTINGS, ["sample"], engine_factory=lambda _: backend)
    assert stale == 0
    assert {r["entity_id"] for r in result.tables["ii_entities"]} == {1, 2, 3, 4}
    assert result.tables["ii_entities"][0]["entity_name"] == "SAMPLE"
    assert any("readlock=shared" in s for s in backend.settings)
    assert backend.disposed == 1


def test_follows_only_declared_source_includes(tmp_path: Path) -> None:
    backend = Backend(tmp_path / "source.sqlite")
    source = archive()
    source.tables["ii_incl_apps"].append(
        {
            "app_id": 2,
            "incl_name": "library",
            "incl_filename": "",
            "incl_version": -1,
            "incl_sequence": 1,
        }
    )
    library = archive().remap({1: 5, 2: 6, 3: 7, 4: 8})
    for row in library.tables["ii_entities"]:
        if row["entity_type"] == "appsource":
            row["entity_name"] = "library"
    backend.seed(source)
    backend.seed(library)
    result, _ = capture(SETTINGS, ["sample"], engine_factory=lambda _: backend)
    assert len(result.tables["ii_applications"]) == 2


def test_stale_dependency_is_symbolic_without_mutating_source(tmp_path: Path) -> None:
    backend = Backend(tmp_path / "source.sqlite")
    source = archive()
    source.tables["ii_dependencies"].append(
        {
            "src_entity_id": 4,
            "src_entity_type": "proc4glsource",
            "rel_class_type": "REFERENCES",
            "dest_entity_id": 999,
            "dest_app_name": "sample",
            "dest_comp_name": "removed",
            "qualified_ref": "N",
            "dependency_origin": "4GL_COMPILER",
        }
    )
    backend.seed(source)
    result, count = capture(SETTINGS, ["sample"], engine_factory=lambda _: backend)
    assert count == 1
    assert result.tables["ii_dependencies"][0]["dest_entity_id"] == 0
    assert backend.rows("ii_dependencies")[0]["dest_entity_id"] == 999


def test_missing_application_never_produces_partial_archive(tmp_path: Path) -> None:
    backend = Backend(tmp_path / "source.sqlite")
    backend.seed(archive())
    with pytest.raises(UnsupportedSource, match="missing_or_ambiguous"):
        capture(SETTINGS, ["sample", "missing"], engine_factory=lambda _: backend)
    assert backend.disposed == 1


def test_live_external_dependency_is_never_normalized_as_deleted(
    tmp_path: Path,
) -> None:
    backend = Backend(tmp_path / "source.sqlite")
    source = archive()
    source.tables["ii_dependencies"].append(
        {
            "src_entity_id": 4,
            "src_entity_type": "proc4glsource",
            "rel_class_type": "REFERENCES",
            "dest_entity_id": 8,
            "dest_app_name": "external",
            "dest_comp_name": "probe",
            "qualified_ref": "Y",
            "dependency_origin": "4GL_COMPILER",
        }
    )
    external = archive().remap({1: 5, 2: 6, 3: 7, 4: 8})
    for row in external.tables["ii_entities"]:
        if row["entity_type"] == "appsource":
            row["entity_name"] = "external"
    backend.seed(source)
    backend.seed(external)
    with pytest.raises(UnsupportedSource, match="live_external_dependency"):
        capture(SETTINGS, ["sample"], engine_factory=lambda _: backend)
    assert backend.rows("ii_dependencies")[0]["dest_entity_id"] == 8

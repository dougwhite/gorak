"""Independent reconstruction, rather than an overlay on the input XML."""

import json
from pathlib import Path

import pytest
from lxml import etree

from gorak.errors import ProjectError
from gorak.importer import signature
from gorak.parser import NS, encode_w4gl, encode_wml, parse_component_node
from gorak.portable_source import (
    legacy_component,
    restore_application,
    restore_component,
    write_companions,
)
from gorak.readable_source import (
    COMPONENT_TYPES,
    decode_component,
    encode_application,
    encode_component,
)
from gorak.source_migration import migrate_source


def write_source(folder: Path, node: etree._Element) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{node.get('name')}.w4gl"
    text, markup = encode_component(node)
    path.write_text(text)
    if markup is not None:
        path.with_suffix(".wml").write_text(markup)
    return path


@pytest.mark.parametrize(
    "fixture",
    [
        "fm_example_frame",
        "fm_complex_frame",
        "uc_example_userclass",
        "p4_example_procedure",
    ],
)
def test_complete_fixture_without_xml_or_cache(tmp_path: Path, fixture: str) -> None:
    original = etree.parse(f"tests/fixtures/{fixture}.xml").find("COMPONENT")
    assert original is not None
    path = write_source(tmp_path / "example", original)
    assert not list(tmp_path.rglob("*.xml"))
    assert signature(restore_component(path)) == signature(original)
    # Neither a stale companion nor an invalid operational cache supplies source.
    cache = tmp_path / ".openroad/example"
    cache.mkdir(parents=True)
    (cache / "example.xml").write_text("invalid")
    companion = path.parent / ".gorak-source/components"
    companion.mkdir(parents=True)
    (companion / f"{path.stem}.xml").write_text("invalid")
    assert signature(restore_component(path)) == signature(original)


@pytest.mark.parametrize("kind", sorted(COMPONENT_TYPES))
def test_each_supported_type(tmp_path: Path, kind: str) -> None:
    node = etree.Element("COMPONENT", name="example", nsmap=NS)
    node.set(f"{{{NS['xsi']}}}type", kind)
    etree.SubElement(node, "versshortremarks").text = "metadata survives"
    if kind in {
        "classsource",
        "proc4glsource",
        "framesource",
        "scriptsource",
        "ghostsource",
    }:
        etree.SubElement(node, "script").text = "\n\tRETURN 1;\n"
    path = write_source(tmp_path, node)
    assert signature(restore_component(path)) == signature(node)


def test_script_and_layout_edits_are_the_only_source(tmp_path: Path) -> None:
    node = etree.parse("tests/fixtures/fm_example_frame.xml").find("COMPONENT")
    assert node is not None
    path = write_source(tmp_path, node)
    path.write_text(path.read_text().replace("initialize()", "initialize(newarg=1)"))
    markup = path.with_suffix(".wml")
    markup.write_text(markup.read_text().replace('width="23999"', 'width="6104"', 1))
    restored = restore_component(path)
    assert "initialize(newarg=1)" in restored.findtext("script", "")
    assert restored.findtext("topform/width") == "6104"


def test_whitespace_and_cdata_terminator(tmp_path: Path) -> None:
    node = etree.fromstring(
        b'<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="frame" xsi:type="framesource"><script> \n</script><topform><name>a&#9;b&#10;c&#13;d</name><script><![CDATA[\nRETURN "]]]]><![CDATA[>";\n]]></script></topform></COMPONENT>'
    )
    path = write_source(tmp_path, node)
    assert signature(restore_component(path)) == signature(node)


def test_unknown_source_is_refused(tmp_path: Path) -> None:
    node = etree.fromstring(
        b'<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="example" xsi:type="proc4glsource"><unrecognized>data</unrecognized></COMPONENT>'
    )
    with pytest.raises(ProjectError, match="Unsupported"):
        write_source(tmp_path, node)


def test_wrong_row_type_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "frame.w4gl"
    path.write_text("source_format=2\n[framesource]\n")
    path.with_suffix(".wml").write_text(
        '<frame source_format="2"><topform><childfields><inclapp/></childfields></topform></frame>'
    )
    with pytest.raises(ProjectError, match="does not derive"):
        decode_component(path)


def test_complete_application(tmp_path: Path) -> None:
    folder = tmp_path / "example"
    folder.mkdir()
    node = etree.fromstring(
        b'<APPLICATION name="example"><versshortremarks>before</versshortremarks><commandline>--mode test</commandline><appflags>17</appflags></APPLICATION>'
    )
    values = encode_application(node)
    (folder / "app.json").write_text(json.dumps(values))
    assert signature(restore_application(folder)) == signature(node)
    values["commandline"] = "--mode changed"
    (folder / "app.json").write_text(json.dumps(values))
    assert restore_application(folder).findtext("commandline") == "--mode changed"


def legacy_project(root: Path) -> Path:
    folder = root / "example"
    folder.mkdir()
    (root / "gorak.json").write_text('{"name":"example"}')
    (folder / "app.json").write_text(
        '{"starting_component":"","description":"","included_applications":[]}'
    )
    xml = Path("tests/fixtures/fm_example_frame.xml")
    node = etree.parse(str(xml)).find("COMPONENT")
    assert node is not None
    component = parse_component_node(node)
    path = folder / f"{component.name}.w4gl"
    path.write_text(
        encode_w4gl(component).replace("initialize()", "initialize(newarg=1)")
    )
    path.with_suffix(".wml").write_text(encode_wml(component) or "")
    write_companions(xml, folder)
    return path


def test_migration_preserves_edits_and_backups(tmp_path: Path) -> None:
    source = legacy_project(tmp_path)
    before = source.read_bytes()
    expected = signature(legacy_component(source))
    operation = migrate_source(tmp_path)
    assert operation is not None
    assert signature(restore_component(source)) == expected
    assert (operation / "before/example" / source.name).read_bytes() == before
    assert not (source.parent / ".gorak-source").exists()
    assert not list(source.parent.rglob("*.xml"))
    assert migrate_source(tmp_path) is None


@pytest.mark.parametrize(
    "marker", ["pull-pending.json", "push-pending.json", "revision-quarantine.json"]
)
def test_migration_respects_unfinished_operations(tmp_path: Path, marker: str) -> None:
    source = legacy_project(tmp_path)
    before = source.read_bytes()
    (tmp_path / ".openroad").mkdir()
    (tmp_path / ".openroad" / marker).write_text("{}")
    with pytest.raises(ProjectError):
        migrate_source(tmp_path)
    assert source.read_bytes() == before


def test_script_internal_carriage_returns(tmp_path: Path) -> None:
    node = etree.fromstring(
        b'<COMPONENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" name="frame" xsi:type="framesource"><script>RETURN 1;&#13;RETURN 2;</script><topform><script>RETURN 1;&#13;RETURN 2;</script></topform></COMPONENT>'
    )
    path = write_source(tmp_path, node)
    restored = restore_component(path)
    assert signature(restored) == signature(node)
    from gorak.xml_writer import document

    transported = etree.fromstring(document([restored])).find("COMPONENT")
    assert transported is not None
    assert signature(transported) == signature(node)


def test_migration_detects_concurrent_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import source_migration

    source = legacy_project(tmp_path)
    original_encoder = encode_component

    def encode_and_edit(
        node: etree._Element, **kwargs: object
    ) -> tuple[str, str | None]:
        result = original_encoder(node)
        source.write_text(source.read_text() + "\n// external edit\n")
        return result

    monkeypatch.setattr(source_migration, "encode_component", encode_and_edit)
    with pytest.raises(ProjectError, match="Source changed"):
        migrate_source(tmp_path)
    assert source.read_text().endswith("// external edit\n")
    assert (source.parent / ".gorak-source").exists()
    assert not (tmp_path / ".openroad/pull-pending.json").exists()


def test_migration_unknown_shape_preserves_all_originals(tmp_path: Path) -> None:
    source = legacy_project(tmp_path)
    companion = source.parent / ".gorak-source/components" / f"{source.stem}.xml"
    companion.write_text(
        companion.read_text().replace(
            "</COMPONENT>", "<unknown>retain</unknown></COMPONENT>"
        )
    )
    originals = {p: p.read_bytes() for p in source.parent.rglob("*") if p.is_file()}
    with pytest.raises(ProjectError):
        migrate_source(tmp_path)
    assert all(p.read_bytes() == data for p, data in originals.items())


def test_migration_keeps_unrecognized_local_files(tmp_path: Path) -> None:
    source = legacy_project(tmp_path)
    note = source.parent / ".gorak-source/notes.txt"
    note.write_text("personal notes")
    before = source.read_bytes()
    with pytest.raises(ProjectError, match="Unrecognized file"):
        migrate_source(tmp_path)
    assert note.read_text() == "personal notes"
    assert source.read_bytes() == before


def test_legacy_frame_can_migrate_with_upgraded_root(tmp_path: Path) -> None:
    source = legacy_project(tmp_path)
    original = source.read_bytes()
    original_markup = source.with_suffix(".wml").read_bytes()
    cache = tmp_path / ".openroad/example"
    cache.mkdir(parents=True)
    companion = source.parent / ".gorak-source/components" / f"{source.stem}.xml"
    (cache / f"{source.stem}.xml").write_bytes(companion.read_bytes())
    migrate_source(tmp_path)
    expected = signature(restore_component(source))
    source.write_bytes(original)
    source.with_suffix(".wml").write_bytes(original_markup)
    migrate_source(tmp_path)
    assert signature(restore_component(source)) == expected

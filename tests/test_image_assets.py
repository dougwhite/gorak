"""Synthetic assets exercise pixels, identity, editing and native reconstruction."""

from dataclasses import replace
from pathlib import Path

import pytest
from lxml import etree
from PIL import Image

from gorak.bitmap_codec import Bitmap, decode, decode_buffer, encode, encode_buffer
from gorak.errors import ProjectError
from gorak.image_assets import (
    AssetWriter,
    export_bitmap,
    externalize,
    read_bitmap,
    resolve,
)
from gorak.importer import signature


def bitmap(origin: str = "art/logo.png", *, mode: str = "RGBA") -> Bitmap:
    pixels = bytes(range(16)) if mode == "RGBA" else bytes(range(12))
    return Bitmap(
        (
            "12:bitmapobject",
            "0",
            "1",
            "9",
            str(len(pixels)),
            f"{len(origin)}:{origin}",
            "0",
            "1",
            "2",
            "0",
            "2",
            "2",
            "4",
            "0",
        ),
        pixels,
        ("0", "0", "0", "0", "0", "-1", "3", "0", "0", "0", "-1:", "-1:"),
    )


@pytest.mark.parametrize("size", [1, 2, 3, 18, 19, 255, 256, 257, 65536])
def test_buffer_runs(size: int) -> None:
    pixels = bytes(range(32)) + b"\xf1" * size + bytes(range(10))
    text = encode_buffer(pixels)
    assert all(len(line) == 64 for line in text.splitlines()[:-1])
    assert decode_buffer(text, 0, len(pixels))[0] == pixels


def test_native_zero_count_and_invalid_runs() -> None:
    assert decode_buffer("R10000", 0, 256)[0] == bytes(256)
    for text, size in [("R2000000", 5), ("rf00", 2), ("ab", 2), ("R500", 20)]:
        with pytest.raises(ProjectError):
            decode_buffer(text, 0, size)


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_pixels_metadata_and_compression_roundtrip(tmp_path: Path, mode: str) -> None:
    original = bitmap(mode=mode)
    ref = export_bitmap(tmp_path, encode(original), "fallback")
    assert ref["src"] == "images/logo.png"
    assert read_bitmap(tmp_path, ref) == original
    image = Image.open(tmp_path / ref["src"])
    assert image.mode == mode
    assert image.getpixel((0, 0)) == ((2, 1, 0, 3) if mode == "RGBA" else (2, 1, 0))


def test_asset_reuse_and_stable_collisions(tmp_path: Path) -> None:
    writer = AssetWriter(tmp_path)
    a = bitmap()
    b = replace(a, pixels=bytes(reversed(a.pixels)))
    assert writer.export(encode(a), "x")["src"] == "images/logo.png"
    assert writer.export(encode(a), "y")["src"] == "images/logo.png"
    assert writer.export(encode(b), "x")["src"] == "images/logo-01.png"
    assert writer.export(encode(b), "z")["src"] == "images/logo-01.png"
    c = bitmap("other/logo.png")
    assert writer.export(encode(c), "x")["src"] == "images/logo-02.png"
    d = bitmap("art/separate.png")
    assert writer.export(encode(d), "x")["src"] == "images/separate.png"


def test_gorak_first_png_preserves_alpha_and_edits(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    path = tmp_path / "images/new.png"
    im = Image.new("RGBA", (2, 1))
    im.putdata([(100, 50, 25, 0), (200, 80, 20, 127)])
    im.save(path)
    obj = read_bitmap(tmp_path, "images/new.png")
    assert obj.pixels == bytes([25, 50, 100, 0, 20, 80, 200, 127])
    assert decode(encode(obj)).pixels == obj.pixels
    node = etree.fromstring(b'<bgbitmap src="images/new.png"/>')
    resolve(node, tmp_path)
    projected = externalize(node, tmp_path, "frame")
    resolve(projected, tmp_path)
    assert signature(projected) == signature(node)


def test_mask_and_mono_unused_bits(tmp_path: Path) -> None:
    a = bitmap()
    header = list(a.header)
    header[4], header[10], header[12] = "4", "9", "2"
    a = replace(a, header=tuple(header), pixels=b"\x00\x7f\xff\x81", mask=b"\x80\x00")
    # Encode normalizes the mask length.
    a = decode(encode(a))
    ref = export_bitmap(tmp_path, encode(a), "x")
    assert read_bitmap(tmp_path, ref) == a


@pytest.mark.parametrize(
    "reference", ["../x.png", "/tmp/x.png", "images/../x.png", "images\\x.png"]
)
def test_references_cannot_escape(tmp_path: Path, reference: str) -> None:
    with pytest.raises(ProjectError):
        read_bitmap(tmp_path, reference)


def test_unknown_bitmap_refused_without_asset(tmp_path: Path) -> None:
    with pytest.raises(ProjectError):
        export_bitmap(tmp_path, "12:bitmapobject\nunknown", "x")
    assert not list(tmp_path.rglob("*.png"))


def test_png_first_reexport_reuses_original_file(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    path = tmp_path / "images/custom.png"
    Image.new("RGBA", (2, 2), (32, 64, 128, 80)).save(path)
    before = path.read_bytes()
    native = read_bitmap(tmp_path, "images/custom.png")
    assert (
        export_bitmap(tmp_path, encode(native), "component")["src"]
        == "images/custom.png"
    )
    assert path.read_bytes() == before
    assert not list(tmp_path.rglob("*.bitmap.json"))


def test_indexed_palette_keeps_native_fourth_channel(tmp_path: Path) -> None:
    a = bitmap()
    header = list(a.header)
    header[4], header[13] = "4", "2"
    header += ["10", "20", "30", "1", "100", "150", "200", "1"]
    a = replace(a, header=tuple(header), pixels=b"\0\1\1\0")
    ref = export_bitmap(tmp_path, encode(a), "x")
    assert Image.open(tmp_path / ref["src"]).mode == "P"
    assert read_bitmap(tmp_path, ref) == a
    im = Image.open(tmp_path / ref["src"])
    palette = im.getpalette()
    assert palette is not None
    palette[:3] = [40, 50, 60]
    im.putpalette(palette)
    im.save(tmp_path / ref["src"])
    restored = read_bitmap(tmp_path, ref)
    assert restored.header[14:18] == ("40", "50", "60", "1")
    assert restored.pixels == a.pixels


def test_empty_native_placeholder_remains_inline(tmp_path: Path) -> None:
    text = (
        "\n".join(
            [
                "12:bitmapobject",
                "0",
                "1",
                "9",
                "0",
                "-1:",
                "0",
                "1",
                "2",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "-1",
                "0",
                "0",
                "0",
                "0",
                "-1:",
                "-1:",
            ]
        )
        + "\n"
    )
    node = etree.Element("bgbitmap")
    etree.SubElement(node, "obj_encoded").text = text
    projected = externalize(node, tmp_path, "example")
    assert etree.tostring(projected) == etree.tostring(node)
    assert not list(tmp_path.rglob("*.png"))


def test_missing_mask_fails_and_edited_image_is_not_overwritten(tmp_path: Path) -> None:
    a = bitmap()
    ref = export_bitmap(tmp_path, encode(a), "x")
    Image.new("RGBA", (2, 2), (255, 255, 255, 255)).save(tmp_path / ref["src"])
    before = (tmp_path / ref["src"]).read_bytes()
    assert export_bitmap(tmp_path, encode(a), "x")["src"] == "images/logo-01.png"
    assert (tmp_path / ref["src"]).read_bytes() == before
    masked = replace(a, mask=b"\0\xff")
    ref = export_bitmap(tmp_path, encode(masked), "x")
    assert read_bitmap(tmp_path, ref).mask == b"\0\xff"
    ref["mask"] = "2x2:invalid"
    with pytest.raises(ProjectError, match="Invalid compressed"):
        read_bitmap(tmp_path, ref)


def test_symlink_asset_refused(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "images/link.png").symlink_to(tmp_path / "outside.png")
    with pytest.raises(ProjectError, match="Symlinked"):
        read_bitmap(tmp_path, "images/link.png")


def test_stylesheet_bitmap_override_externalizes_and_restores(tmp_path: Path) -> None:
    import json

    from gorak import native_styles
    from gorak.component_defaults import write_component_defaults

    folder = tmp_path / "example"
    folder.mkdir()
    source = folder / "panel.w4gl"
    native = encode(bitmap())
    values = {
        "groups": {
            "buttonfield": {"styles": {"style1": {"bgbitmap": {"obj_encoded": native}}}}
        }
    }
    write_component_defaults(source, values)
    path = source.with_suffix(".fielddefaults.json")
    data = json.loads(path.read_text())
    value = data["groups"]["buttonfield"]["styles"]["style1"]["bgbitmap"]
    assert value == {
        "src": "images/logo.png",
        "path": "art/logo.png",
        "palette-count": "0",
    }
    restored = native_styles.read(path)
    assert (
        decode(
            restored["groups"]["buttonfield"]["styles"]["style1"]["bgbitmap"][
                "obj_encoded"
            ]
        )
        == bitmap()
    )


def test_class_icons_order_missing_metadata_and_unknown_extension(
    tmp_path: Path,
) -> None:
    from gorak.class_icons import collection, extract_icons, overlay_icons
    from gorak.parser import encode_w4gl, parse_component_node
    from gorak.style_values import XSI

    (tmp_path / "images").mkdir()
    Image.new("RGBA", (2, 2), (100, 50, 20, 255)).save(tmp_path / "images/icon.png")
    data = {
        "entries": [
            {"id": "3", "src": "images/icon.png"},
            {"id": "1", "src": "images/icon.png"},
        ]
    }
    node = etree.fromstring(
        b'<COMPONENT name="example"><taggedvalues><row><name>class_icons</name><value>(icons/example)</value></row></taggedvalues></COMPONENT>'
    )
    node.set(XSI, "classsource")
    node.insert(0, collection(data, "(icons/example)"))
    source = tmp_path / "example.w4gl"
    source.write_text(encode_w4gl(parse_component_node(node)))
    assert extract_icons(node) == data
    assert "[[icons.entries]]" in source.read_text()
    assert not list(tmp_path.glob("*.icons.json"))
    overlay_icons(node, source)
    assert [
        r.findtext("enumvalue")
        for r in node.findall("extension/row")[1].findall("choiceitems/row")
    ] == ["3", "1"]
    assert len(list(node.iter("obj_encoded"))) == 2
    source.write_text(
        '[classsource]\n[taggedvalues]\nclass_icons = "(icons/example)"\n'
    )
    with pytest.raises(ProjectError, match="Missing class icons"):
        overlay_icons(node, source)
    node.find("extension").append(etree.Element("unknown"))
    with pytest.raises(ProjectError):
        extract_icons(node)


def test_shared_png_edits_affect_all_references_and_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import sync_plan
    from gorak.connection import OpenRoadConnection
    from gorak.domain import Application
    from gorak.portable_source import restore_application, restore_component
    from gorak.xml_writer import document

    folder = tmp_path / "example"
    (folder / "images").mkdir(parents=True)
    (folder / "app.json").write_text("{}")
    for name in ("first", "second"):
        (folder / f"{name}.w4gl").write_text("[framesource]\n===\n")
        (folder / f"{name}.wml").write_text(
            '<frame><topform><bgbitmap src="images/shared.png"/></topform></frame>'
        )
    image = folder / "images/shared.png"
    Image.new("RGB", (2, 2), (100, 50, 25)).save(image)

    def native() -> bytes:
        return document(
            [
                restore_application(folder),
                *[restore_component(p) for p in sorted(folder.glob("*.w4gl"))],
            ]
        )

    baseline = native()
    cache = tmp_path / ".openroad/example/example.xml"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(baseline)
    monkeypatch.setattr(
        sync_plan, "read_applications", lambda _: [Application("example", "", "")]
    )
    monkeypatch.setattr(
        sync_plan, "backup_application_xml", lambda c, a, p: p.write_bytes(baseline)
    )
    connection = OpenRoadConnection("local", "node", "db", None)
    assert all(
        c.action == "unchanged" for c in sync_plan.plan_project(connection, tmp_path)
    )
    Image.new("RGB", (2, 2), (110, 60, 30)).save(image)
    remote = native()
    changes = {c.key: c.action for c in sync_plan.plan_project(connection, tmp_path)}
    assert changes["example/first"] == changes["example/second"] == "push"
    monkeypatch.setattr(
        sync_plan, "backup_application_xml", lambda c, a, p: p.write_bytes(remote)
    )
    Image.new("RGB", (2, 2), (0, 0, 255)).save(image)
    changes = {c.key: c.action for c in sync_plan.plan_project(connection, tmp_path)}
    assert changes["example/first"] == changes["example/second"] == "conflict"
    image.unlink()
    invalid_changes = sync_plan.plan_project(connection, tmp_path)
    for change in invalid_changes:
        if change.key in {"example/first", "example/second"}:
            assert change.action == "conflict" and change.disk == "invalid"
            assert "Cannot read image" in change.reason


def test_large_inline_source_and_parser_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gorak import source_xml
    from gorak.wml_writer import parse_markup

    payload = (
        "<frame><topform><bgbitmap><obj_encoded>"
        + ("a" * 10_100_000)
        + "</obj_encoded></bgbitmap></topform></frame>"
    )
    assert (
        len(parse_markup(payload).findtext("topform/bgbitmap/obj_encoded"))
        == 10_100_000
    )
    with pytest.raises(ProjectError, match="document type"):
        source_xml.from_bytes(
            b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///not-readable">]><x>&e;</x>'
        )
    with pytest.raises(ProjectError, match="nesting"):
        source_xml.from_bytes(b"<x>" * 257 + b"</x>" * 257)
    monkeypatch.setattr(source_xml, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(ProjectError, match="document limit"):
        source_xml.from_bytes(b"<x>too large</x>")


def test_stylesheet_promotion_keeps_assets_and_dry_run_is_read_only(
    tmp_path: Path,
) -> None:
    import json

    from gorak import native_styles, style_commands
    from gorak.component_defaults import write_component_defaults
    from gorak.safe_pull import fingerprint

    folder = tmp_path / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}")
    source = folder / "panel.w4gl"
    source.write_text("[framesource]\n===\n")
    write_component_defaults(
        source,
        {
            "groups": {
                "buttonfield": {
                    "styles": {
                        "style1": {"bgbitmap": {"obj_encoded": encode(bitmap())}}
                    }
                }
            }
        },
    )
    expected = native_styles.frame_styles(source)
    before = fingerprint(tmp_path)
    style_commands.maintain(tmp_path, "compact", dry_run=True)
    assert fingerprint(tmp_path) == before
    style_commands.maintain(tmp_path, "compact")
    assert native_styles.frame_styles(source) == expected
    assert (tmp_path / "images/logo.png").is_file()
    assert (
        "src"
        in json.loads((tmp_path / "field_defaults.json").read_text())["groups"][
            "buttonfield"
        ]["styles"]["style1"]["bgbitmap"]
    )


def test_nondefault_fields_survive_without_sidecars(tmp_path: Path) -> None:
    a = bitmap()
    header, tail = list(a.header), list(a.tail)
    for i in (1, 2, 3, 6, 7, 8, 9):
        header[i] = str(10 + i)
    for i in (0, 1, 2, 3, 4, 7, 8, 9):
        tail[i] = str(20 + i)
    header[5], header[12] = "-1:", "12"
    tail[6] = "2"
    a = replace(a, header=tuple(header), tail=tuple(tail))
    ref = export_bitmap(tmp_path, encode(a), "anonymous")
    assert read_bitmap(tmp_path, ref) == a
    assert ref["native-h5"] == "-1"
    assert ref["path"] == ""
    assert {p.suffix for p in tmp_path.rglob("*") if p.is_file()} == {".png"}


def test_plain_rgba_needs_only_src_and_path(tmp_path: Path) -> None:
    (tmp_path / "images").mkdir()
    Image.new("RGBA", (2, 2), (20, 40, 60, 80)).save(tmp_path / "images/new.png")
    a = read_bitmap(tmp_path, {"src": "images/new.png", "path": r"art\new.png"})
    ref = export_bitmap(tmp_path, encode(a), "new")
    assert set(ref) == {"src", "path"}
    assert read_bitmap(tmp_path, ref) == a


def test_mask_is_self_contained_and_resize_is_rejected(tmp_path: Path) -> None:
    a = decode(encode(replace(bitmap(), mask=b"\x80\x7f")))
    ref = export_bitmap(tmp_path, encode(a), "mask")
    assert read_bitmap(tmp_path, ref) == a
    assert not list(tmp_path.rglob("*.mask.png"))
    Image.new("RGBA", (3, 2)).save(tmp_path / ref["src"])
    with pytest.raises(ProjectError, match="Resize"):
        read_bitmap(tmp_path, ref)


def test_staged_export_uses_reference_identity(tmp_path: Path) -> None:
    import shutil

    source, stage = tmp_path / "source", tmp_path / "stage"
    source.mkdir()
    stage.mkdir()
    first = bitmap("one/logo.png")
    second = bitmap("two/logo.png")
    writer = AssetWriter(source)
    refs = [writer.export(encode(first), "x"), writer.export(encode(second), "x")]
    root = etree.Element("frame")
    for ref in refs:
        etree.SubElement(root, "bgbitmap", ref)
    (source / "frame.wml").write_bytes(etree.tostring(root))
    shutil.copytree(source / "images", stage / "images")
    writer = AssetWriter(stage, origins_from=source)
    assert writer.export(encode(second), "x") == refs[1]
    assert writer.export(encode(first), "x") == refs[0]
    assert len(list(stage.rglob("*.png"))) == 2


def test_invalid_reference_attributes_fail(tmp_path: Path) -> None:
    from gorak.image_assets import pack

    ref = export_bitmap(tmp_path, encode(bitmap()), "x")
    for extra in (
        {"unknown": "1"},
        {"padding": pack(b"\0")},
        {"palette": pack(bytes(10000))},
        {"native-h5": "-1"},
        {"palette-count": "-1"},
        {"mask": "2x2:not base64"},
    ):
        with pytest.raises(ProjectError):
            read_bitmap(tmp_path, {**ref, **extra})


def test_stylesheet_reference_preserves_order_annotations(tmp_path: Path) -> None:
    from gorak.image_assets import stylesheet_assets

    native = {"obj_encoded": encode(bitmap()), "$order": ["obj_encoded"]}
    projected = stylesheet_assets(native, tmp_path, exporting=True)
    assert projected["$order"] == ["src"]
    assert stylesheet_assets(projected, tmp_path, exporting=False) == native


@pytest.mark.parametrize(
    "icons",
    [
        {
            "entries": [
                {"id": "1", "src": "images/a.png"},
                {"id": "1", "src": "images/b.png"},
            ]
        },
        {"entries": [{"id": "1", "src": "images/a.png", "unknown": "x"}]},
        {"entries": "invalid"},
        {"entries": [], "key": "duplicate"},
    ],
)
def test_invalid_inline_icon_collections(icons: dict[str, object]) -> None:
    from gorak.class_icons import collection

    with pytest.raises(ProjectError):
        collection(icons, "(icons/example)")


def test_inline_icons_empty_collection_and_key_edit(tmp_path: Path) -> None:
    from gorak.class_icons import extract_icons
    from gorak.parser import encode_w4gl, parse_component_node
    from gorak.portable_source import restore_component

    source = tmp_path / "example.w4gl"
    source.write_text(
        '[classsource]\nsuperclass = "userobject"\n'
        '[taggedvalues]\nclass_icons = "(icons/renamed)"\n'
        "[icons]\nentries = []\n"
    )
    native = restore_component(source)
    assert extract_icons(native) == {"entries": []}
    assert (
        native.findtext("extension/row/choiceitems/row/enumtext") == "(icons/renamed)"
    )
    source.write_text(encode_w4gl(parse_component_node(native)))
    assert signature(restore_component(source)) == signature(native)


@pytest.mark.parametrize(
    "source",
    [
        "[classsource]\n[icons]\nentries = []\n",
        '[proc4glsource]\n[taggedvalues]\nclass_icons = "icons"\n[icons]\nentries = []\n',
        '[classsource]\nicons = "invalid"\n',
    ],
)
def test_inline_icons_require_class_and_tagged_key(tmp_path: Path, source: str) -> None:
    from gorak.portable_source import restore_component

    path = tmp_path / "example.w4gl"
    path.write_text(source)
    with pytest.raises(ProjectError):
        restore_component(path)


def test_all_builtin_images_roundtrip_without_local_assets(tmp_path: Path) -> None:
    from gorak import builtin_images

    for name in builtin_images.catalog():
        ref = {"src": "builtin:" + name}
        original = read_bitmap(tmp_path, ref)
        # The historical filename identifies a default; pixels must also match.
        exported = export_bitmap(tmp_path, encode(original), "unused")
        assert exported["src"] == ref["src"]
        assert read_bitmap(tmp_path, exported) == original
        assert builtin_images.image_bytes(ref["src"])
    assert not list(tmp_path.iterdir())


def test_builtin_match_requires_pixels_and_original_name(tmp_path: Path) -> None:
    a = read_bitmap(tmp_path, "builtin:pal_icon6")
    changed = replace(a, pixels=bytes([a.pixels[0] ^ 255]) + a.pixels[1:])
    assert export_bitmap(tmp_path, encode(changed), "x")["src"].startswith("images/")
    header = list(a.header)
    header[5] = "12:separate.xbm"
    independent = replace(a, header=tuple(header))
    assert (
        export_bitmap(tmp_path, encode(independent), "x")["src"]
        == "images/separate.png"
    )


def test_builtin_preserves_reference_native_overrides(tmp_path: Path) -> None:
    original = read_bitmap(
        tmp_path,
        {
            "src": "builtin:class-icon-16",
            "path": r"art\1616_2.bmp",
            "native-t7": "1",
            "native-t8": "8",
        },
    )
    exported = export_bitmap(tmp_path, encode(original), "unused")
    assert exported["src"] == "builtin:class-icon-16"
    assert exported["path"] == r"art\1616_2.bmp"
    assert read_bitmap(tmp_path, exported) == original
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "ref",
    [
        "builtin:missing",
        "builtin:../pal_icon6",
        "builtin:/pal_icon6",
        "builtin:pal_icon6.png",
    ],
)
def test_unknown_builtin_is_refused(tmp_path: Path, ref: str) -> None:
    with pytest.raises(ProjectError, match="Unknown built-in"):
        read_bitmap(tmp_path, ref)


@pytest.mark.parametrize("location", ["application", "frame"])
def test_unloaded_window_icon_full_roundtrip(tmp_path: Path, location: str) -> None:
    import json

    from gorak.contract_source import equivalent
    from gorak.export import application_metadata
    from gorak.parser import parse_application_xml
    from gorak.portable_source import restore_application, restore_component
    from gorak.style_values import XSI
    from tests.native_source import write_component

    unloaded = (
        "\n".join(
            [
                "12:bitmapobject",
                "0",
                "1",
                "9",
                "0",
                "-1:",
                "0",
                "1",
                "2",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "-1",
                "0",
                "0",
                "0",
                "0",
                "-1:",
                "-1:",
            ]
        )
        + "\n"
    )
    folder = tmp_path / "example"
    folder.mkdir()
    node = etree.Element(
        "APPLICATION" if location == "application" else "COMPONENT", name="example"
    )
    etree.SubElement(
        etree.SubElement(node, "windowicon"), "obj_encoded"
    ).text = unloaded
    if location == "application":
        projected = externalize(node, folder, "example")
        root = etree.Element("OPENROAD")
        root.append(projected)
        parsed = parse_application_xml(root)
        metadata = application_metadata(
            parsed.application, included_applications=parsed.included_applications
        )
        (folder / "app.json").write_text(json.dumps(metadata))
        restored = restore_application(folder)
        assert metadata["window_icon"] == unloaded
    else:
        from gorak import native_styles

        node.set(XSI, "framesource")
        etree.SubElement(node, "topform")
        node.append(native_styles.decode(native_styles.baseline()))
        source = folder / "example.w4gl"
        write_component(source, node)
        restored = restore_component(source)
        assert equivalent(node, restored)
    assert restored.findtext("windowicon/obj_encoded") == unloaded
    assert not list(folder.rglob("*.png"))


@pytest.mark.parametrize("staged", [False, True])
def test_nested_asset_reference_reused(tmp_path: Path, staged: bool) -> None:
    import json
    import shutil

    from gorak.image_assets import AssetWriter

    folder = tmp_path / "original"
    folder.mkdir()
    native = bitmap()
    ref = export_bitmap(folder, encode(native), "unused")
    nested = folder / "images/sub/logo.png"
    nested.parent.mkdir()
    (folder / ref["src"]).rename(nested)
    ref["src"] = "images/sub/logo.png"
    (folder / "app.json").write_text(json.dumps({"window_icon": ref}))
    target = tmp_path / "stage" if staged else folder
    if staged:
        shutil.copytree(folder / "images", target / "images")
    writer = AssetWriter(target, origins_from=folder if staged else None)
    assert writer.export(encode(native), "unused") == ref
    assert read_bitmap(target, ref) == native
    assert list((target / "images").rglob("*.png")) == [target / ref["src"]]


def test_writer_cache_observes_image_edits_and_symlinks(tmp_path: Path) -> None:
    writer = AssetWriter(tmp_path)
    native = encode(bitmap())
    first = writer.export(native, "first")
    path = tmp_path / first["src"]
    Image.new("RGBA", (2, 2), "red").save(path)
    second = writer.export(native, "second")
    assert second["src"] != first["src"]
    (tmp_path / second["src"]).unlink()
    (tmp_path / second["src"]).symlink_to(path)
    with pytest.raises(ProjectError, match="Symlink"):
        writer.export(native, "second")


def test_anonymous_writer_cache_keeps_owner_names(tmp_path: Path) -> None:
    writer = AssetWriter(tmp_path)
    native = encode(bitmap(""))
    assert writer.export(native, "first")["src"] == "images/first.png"
    assert writer.export(native, "second")["src"] == "images/second.png"
    assert writer.export(native, "first")["src"] == "images/first.png"


@pytest.mark.parametrize("separator", ["\n", "\r", "\x85", "\u2028"])
def test_reference_rejects_native_line_separators(
    tmp_path: Path, separator: str
) -> None:
    (tmp_path / "images").mkdir()
    Image.new("RGBA", (1, 1)).save(tmp_path / "images/test.png")
    with pytest.raises(ProjectError, match="line breaks"):
        read_bitmap(
            tmp_path,
            {"src": "images/test.png", "path": "art" + separator + "image.png"},
        )

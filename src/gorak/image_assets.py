"""PNG assets and self-contained bitmap references; no per-image sidecars."""

import base64
import binascii
import hashlib
import json
import re
import tomllib
import zlib
from copy import deepcopy
from io import BytesIO
from pathlib import Path, PureWindowsPath
from typing import Any

from lxml import etree
from PIL import Image

from .bitmap_codec import MAX_BYTES, MAX_PIXELS, Bitmap, decode, encode, is_empty
from .errors import ProjectError


def asset_path(folder: Path, name: str) -> Path:
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise ProjectError("Image references must be application-relative paths")
    parts = Path(name).parts
    if (
        len(parts) < 2
        or parts[0] != "images"
        or ".." in parts
        or Path(name).is_absolute()
    ):
        raise ProjectError("Image references must stay inside application images/")
    path = folder / name
    if any((folder / Path(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)):
        raise ProjectError("Symlinked image assets are unsupported")
    if not path.resolve().is_relative_to(folder.resolve()):
        raise ProjectError("Image reference escapes application")
    return path


def png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", compress_level=9)
    return output.getvalue()


def project(bitmap: Bitmap) -> bytes:
    w, h = bitmap.width, bitmap.height
    size = w * h
    header = list(bitmap.header)
    palette = [list(map(int, header[i : i + 4])) for i in range(14, len(header), 4)]
    if int(header[12]) == 2 and len(bitmap.pixels) == ((w + 7) // 8) * h:
        image = Image.frombytes("1", (w, h), bytes(v ^ 255 for v in bitmap.pixels))
    elif len(bitmap.pixels) == size and palette:
        image = Image.frombytes("P", (w, h), bitmap.pixels)
        image.putpalette([c for entry in palette for c in entry[:3]])
    elif len(bitmap.pixels) == size * 3:
        image = Image.frombytes("RGB", (w, h), bitmap.pixels, "raw", "BGR")
    elif len(bitmap.pixels) == size * 4:
        image = Image.frombytes("RGBA", (w, h), bitmap.pixels, "raw", "BGRA")
    else:
        raise ProjectError("Unsupported bitmap pixel layout")
    return png_bytes(image)


def read_png(path: Path) -> Image.Image:
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ProjectError("Image file exceeds supported bounds")
        with Image.open(path) as image:
            if (
                image.format != "PNG"
                or image.width * image.height > MAX_PIXELS
                or getattr(image, "n_frames", 1) != 1
            ):
                raise ProjectError("Expected a bounded, single-image PNG")
            image.load()
            return image.copy()
    except (OSError, ValueError, Image.DecompressionBombError) as ex:
        raise ProjectError(f"Cannot read image {path}: {ex}") from ex


# These are measured serialization defaults, not invented system attribute names.
HEADER_DEFAULTS = {1: "0", 2: "1", 3: "9", 6: "0", 7: "1", 8: "2", 9: "0"}
TAIL_DEFAULTS = {0: "0", 1: "0", 2: "0", 3: "0", 4: "0", 7: "0", 8: "0", 9: "0"}
REFERENCE_KEYS = (
    {
        "src",
        "path",
        "native-flags",
        "native-pixeltype",
        "palette-count",
        "palette",
        "palette-flags",
        "padding",
        "mask",
        "native-h5",
    }
    | {f"native-h{i}" for i in HEADER_DEFAULTS}
    | {f"native-t{i}" for i in TAIL_DEFAULTS}
)


def pack(data: bytes) -> str:
    return base64.b64encode(zlib.compress(data, 9)).decode("ascii")


def unpack(value: str, limit: int) -> bytes:
    try:
        if len(value) > MAX_BYTES * 2:
            raise ValueError("Encoded bitmap attribute exceeds bounds")
        compressed = base64.b64decode(value, validate=True)
        decoder = zlib.decompressobj()
        result = decoder.decompress(compressed, limit + 1)
        if len(result) > limit or not decoder.eof or decoder.unused_data:
            raise ValueError("Invalid or oversized bitmap attribute")
        return result
    except (ValueError, zlib.error, binascii.Error) as ex:
        raise ProjectError(f"Invalid compressed bitmap attribute: {ex}") from ex


def reference_fields(bitmap: Bitmap, image: Image.Image) -> dict[str, str]:
    """Keep only information that the PNG and measured defaults cannot supply."""
    h, t = bitmap.header, bitmap.tail
    result = {"path": bitmap.origin}
    # Empty and null native filenames are distinct.
    if h[5] == "-1:":
        result["native-h5"] = "-1"
    flags = "2" if image.mode == "1" else "12" if bitmap.mask is not None else "4"
    if h[12] != flags:
        result["native-flags"] = h[12]
    pixeltype = {"1": "0", "P": "0", "RGB": "1", "RGBA": "3"}[image.mode]
    if t[6] != pixeltype:
        result["native-pixeltype"] = t[6]
    for i, default in HEADER_DEFAULTS.items():
        if h[i] != default:
            result[f"native-h{i}"] = h[i]
    for i, default in TAIL_DEFAULTS.items():
        if t[i] != default:
            result[f"native-t{i}"] = t[i]
    count = int(h[13])
    default_count = (
        len(image.getpalette() or []) // 3
        if image.mode == "P"
        else 0
        if image.mode == "1"
        else 256
    )
    if count != default_count:
        result["palette-count"] = str(count)
    palette = bytes(map(int, h[14:]))
    extra = palette[3::4] if image.mode == "P" else palette
    if any(extra):
        result["palette-flags" if image.mode == "P" else "palette"] = pack(extra)
    if image.mode == "1" and bitmap.width % 8:
        stride = (bitmap.width + 7) // 8
        padding = bytes(
            bitmap.pixels[(y + 1) * stride - 1] & ((1 << (8 - bitmap.width % 8)) - 1)
            for y in range(bitmap.height)
        )
        if any(padding):
            result["padding"] = pack(padding)
    if bitmap.mask is not None:
        result["mask"] = f"{bitmap.width}x{bitmap.height}:" + pack(bitmap.mask)
    return result


def validate_reference(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        return {"src": value}
    if (
        not isinstance(value, dict)
        or "src" not in value
        or set(value) - REFERENCE_KEYS
        or any(not isinstance(v, str) for v in value.values())
    ):
        raise ProjectError("Invalid bitmap reference attributes")
    return dict(value)


def encode_icon(folder: Path, reference: str | dict[str, str]) -> str:
    """Keep unloaded native icons inline; resolve populated image references."""
    if isinstance(reference, str) and is_empty(reference):
        return reference
    return encode(read_bitmap(folder, reference))


def read_bitmap(folder: Path, reference: str | dict[str, str]) -> Bitmap:
    ref = validate_reference(reference)
    if ref["src"].startswith("builtin:"):
        from . import builtin_images

        item = builtin_images.entry(ref["src"])
        ref.setdefault("path", str(item["path"]))
        with Image.open(BytesIO(builtin_images.image_bytes(ref["src"]))) as source:
            source.load()
            image = source.copy()
    else:
        path = asset_path(folder, ref["src"])
        if path.with_suffix(path.suffix + ".bitmap.json").exists():
            raise ProjectError(
                "Obsolete bitmap sidecar; re-export this application before using bitmap references"
            )
        image = read_png(path)
    if image.mode not in {"1", "P", "RGB", "RGBA"} or "transparency" in image.info:
        image = image.convert("RGBA")
    w, h = image.size
    try:
        count = int(
            ref.get(
                "palette-count",
                str(
                    len(image.getpalette() or []) // 3
                    if image.mode == "P"
                    else 0
                    if image.mode == "1"
                    else 256
                ),
            )
        )
        if not 0 <= count <= 256:
            raise ValueError("Invalid bitmap palette count")
        palette = bytearray(count * 4)
        if image.mode == "P":
            if "palette" in ref:
                raise ValueError("Indexed PNG uses palette-flags, not palette")
            colors = image.getpalette() or []
            if len(colors) < count * 3 or max(image.tobytes(), default=0) >= count:
                raise ValueError("PNG palette does not match bitmap reference")
            fourth = (
                unpack(ref["palette-flags"], count)
                if "palette-flags" in ref
                else bytes(count)
            )
            if len(fourth) != count:
                raise ValueError("Palette flags length differs from palette")
            for i in range(count):
                palette[i * 4 : i * 4 + 4] = (
                    bytes(colors[i * 3 : i * 3 + 3]) + fourth[i : i + 1]
                )
            pixels = image.tobytes()
        else:
            if "palette-flags" in ref:
                raise ValueError("Palette flags require an indexed PNG")
            if "palette" in ref:
                palette = bytearray(unpack(ref["palette"], count * 4))
                if len(palette) != count * 4:
                    raise ValueError("Native palette length differs from palette count")
            if image.mode == "1":
                pixels_array = bytearray(v ^ 255 for v in image.tobytes())
                if w % 8:
                    padding = (
                        unpack(ref["padding"], h) if "padding" in ref else bytes(h)
                    )
                    if len(padding) != h:
                        raise ValueError("Padding height differs from PNG")
                    stride, bits = (w + 7) // 8, (1 << (8 - w % 8)) - 1
                    for y, value in enumerate(padding):
                        if value & ~bits:
                            raise ValueError("Invalid unused padding bits")
                        i = (y + 1) * stride - 1
                        pixels_array[i] = (pixels_array[i] & ~bits) | value
                elif "padding" in ref:
                    raise ValueError("Padding requires a partial monochrome byte")
                pixels = bytes(pixels_array)
            else:
                if "padding" in ref:
                    raise ValueError("Padding requires a monochrome PNG")
                pixels = image.tobytes("raw", "BGR" if image.mode == "RGB" else "BGRA")
        mask = None
        if "mask" in ref:
            size, data = ref["mask"].split(":", 1)
            if size != f"{w}x{h}":
                raise ValueError(
                    "Resize requires removing or replacing the native mask"
                )
            mask = unpack(data, MAX_BYTES)
            if not mask:
                raise ValueError("Empty native mask")
        origin = ref.get("path", ref["src"])
        filename = f"{len(origin)}:{origin}"
        if "native-h5" in ref:
            if ref["native-h5"] != "-1" or origin:
                raise ValueError("Null filename requires an empty path")
            filename = "-1:"
        header = [
            "12:bitmapobject",
            "0",
            "1",
            "9",
            str(len(pixels)),
            filename,
            "0",
            "1",
            "2",
            "0",
            str(w),
            str(h),
            ref.get(
                "native-flags",
                "2" if image.mode == "1" else "12" if mask is not None else "4",
            ),
            str(count),
        ]
        tail = ["0"] * 5 + [
            str(len(mask)) if mask is not None else "-1",
            ref.get(
                "native-pixeltype",
                {"1": "0", "P": "0", "RGB": "1", "RGBA": "3"}[image.mode],
            ),
            "0",
            "0",
            "0",
            "-1:",
            "-1:",
        ]
        for i in HEADER_DEFAULTS:
            header[i] = ref.get(f"native-h{i}", header[i])
            int(header[i])
        for i in TAIL_DEFAULTS:
            tail[i] = ref.get(f"native-t{i}", tail[i])
        header.extend(map(str, palette))
        # These fields are already constructed from bounded PNG pixels. Validate
        # native overrides directly; serializing megabytes of pixels proves
        # nothing more about them.
        if any(v.splitlines() != [v] for v in [*header, *tail]):
            raise ValueError("Native bitmap fields cannot contain line breaks")
        if int(header[12]) not in {2, 4, 12}:
            raise ValueError("Unsupported bitmap format or palette")
        if w <= 0 or h <= 0 or w * h > MAX_PIXELS or len(pixels) > MAX_BYTES:
            raise ValueError("Bitmap dimensions exceed supported bounds")
        for native_value in tail[:10]:
            int(native_value)
        return Bitmap(tuple(header), pixels, tuple(tail), mask)
    except (ValueError, TypeError, KeyError) as ex:
        raise ProjectError(f"Invalid bitmap reference: {ex}") from ex


class AssetWriter:
    """Allocate names within one export, consulting existing source references."""

    def __init__(self, folder: Path, *, origins_from: Path | None = None):
        self.folder = folder
        self.origins: dict[str, set[str]] = {}
        self._candidates: dict[str, set[str]] | None = None
        self._occupied: set[str] = set()
        self._exported: dict[
            tuple[bytes, str], tuple[dict[str, str], tuple[int, int, int] | None]
        ] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if isinstance(value.get("src"), str):
                    self.origins.setdefault(value["src"], set()).add(
                        str(value.get("path", value["src"]))
                    )
                for v in value.values():
                    visit(v)
            elif isinstance(value, list):
                for v in value:
                    visit(v)

        from .source_xml import from_bytes

        origin_folder = origins_from or folder
        for path in origin_folder.iterdir() if origin_folder.exists() else []:
            if not path.is_file() or path.is_symlink():
                continue
            try:
                if path.suffix == ".json":
                    visit(json.loads(path.read_text()))
                elif path.suffix == ".w4gl":
                    visit(tomllib.loads(path.read_text().split("===", 1)[0]))
                elif path.suffix == ".wml":
                    for node in from_bytes(path.read_bytes()).iter():
                        visit(dict(node.attrib))
            except (ValueError, etree.XMLSyntaxError):
                continue  # Invalid source is never grounds to overwrite an asset.

    def _index(self) -> None:
        directory = self.folder / "images"
        if directory.is_symlink():
            raise ProjectError("Symlinked image directory")
        directory.mkdir(parents=True, exist_ok=True)
        self._candidates = {}
        self._occupied = {p.name.casefold() for p in directory.iterdir()}
        for candidate in sorted(directory.rglob("*.png")):
            name = candidate.relative_to(self.folder).as_posix()
            asset_path(self.folder, name)
            for origin in self.origins.get(name, {name}):
                self._candidates.setdefault(origin, set()).add(name)

    def _remember(self, key: tuple[bytes, str], ref: dict[str, str]) -> dict[str, str]:
        stamp = None
        if not ref["src"].startswith("builtin:"):
            stat = asset_path(self.folder, ref["src"]).stat()
            stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        self._exported[key] = (dict(ref), stamp)
        return ref

    def export(self, text: str, fallback: str) -> dict[str, str]:
        # Digest keys bound memory independently of the serialized image size.
        # Anonymous images still use their owner when allocating a filename.
        header_lines = text.split("\n", 6)
        origin_line = header_lines[5].rstrip("\r") if len(header_lines) > 5 else ""
        key = (
            hashlib.sha256(text.encode()).digest(),
            fallback if origin_line in {"0:", "-1:"} else "",
        )
        cached = self._exported.get(key)
        if cached is not None:
            ref, stamp = cached
            if stamp is None:
                return dict(ref)
            path = asset_path(self.folder, ref["src"])
            if path.exists():
                stat = path.stat()
                if stamp == (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size):
                    return dict(ref)
        bitmap = decode(text)
        data = project(bitmap)
        with Image.open(BytesIO(data)) as image:
            fields = reference_fields(bitmap, image)
        origin = bitmap.origin
        from . import builtin_images

        builtin = builtin_images.match(data, origin)
        if builtin:
            if fields.get("path") == builtin_images.entry(builtin)["path"]:
                fields.pop("path")
            return self._remember(key, {"src": builtin, **fields})
        base = (
            re.sub(
                r"[^A-Za-z0-9_.-]",
                "-",
                PureWindowsPath(origin).stem if origin else fallback,
            ).strip(".-")[:100]
            or "image"
        )
        directory = self.folder / "images"
        if directory.is_symlink():
            raise ProjectError("Symlinked image directory")
        if self._candidates is None:
            self._index()
        assert self._candidates is not None
        for name in sorted(self._candidates.get(origin, ())):
            candidate = asset_path(self.folder, name)
            if not origin and not re.fullmatch(
                re.escape(base) + r"(?:-\d+)?", candidate.stem
            ):
                continue
            try:
                # Reconstruct with this reference's native fields; pixel assets
                # may be shared while the references retain distinct metadata.
                ref = {"src": name, **fields}
                restored = read_bitmap(self.folder, ref)
                if restored == bitmap:
                    self.origins.setdefault(name, set()).add(origin)
                    return self._remember(key, ref)
            except ProjectError:
                continue
        occupied = self._occupied
        index = 0
        while True:
            name = base + (f"-{index:02d}" if index else "") + ".png"
            if name.casefold() not in occupied and not (directory / name).exists():
                break
            index += 1
        occupied.add(name.casefold())
        (directory / name).write_bytes(data)
        name = "images/" + name
        self.origins.setdefault(name, set()).add(origin)
        self._candidates.setdefault(origin, set()).add(name)
        return self._remember(key, {"src": name, **fields})


def export_bitmap(folder: Path, text: str, fallback: str) -> dict[str, str]:
    return AssetWriter(folder).export(text, fallback)


def externalize(
    node: etree._Element,
    folder: Path,
    owner: str,
    *,
    origins_from: Path | None = None,
    writer: AssetWriter | None = None,
) -> etree._Element:
    result = deepcopy(node)
    writer = writer or AssetWriter(folder, origins_from=origins_from)
    for encoded in list(result.iter("obj_encoded")):
        if any(parent.tag == "fielddefaults" for parent in encoded.iterancestors()):
            continue
        if not (encoded.text or "").startswith("12:bitmapobject") or is_empty(
            encoded.text or ""
        ):
            continue
        ref = writer.export(encoded.text or "", asset_label(encoded, owner))
        parent = encoded.getparent()
        if parent is None or len(parent) != 1:
            raise ProjectError("Bitmap reference cannot be combined with inline data")
        parent.remove(encoded)
        parent.attrib.update(ref)
    return result


def asset_label(encoded: etree._Element, owner: str) -> str:
    """Name anonymous objects by their component and field, not document order."""
    parts = []
    for parent in encoded.iterancestors():
        if parent.tag in {"COMPONENT", "APPLICATION"}:
            owner = parent.get("name", owner)
            break
        label = parent.findtext("name") or parent.findtext("enumvalue")
        if not label:
            label = str(parent.tag)
            if parent.tag == "row":
                container = parent.getparent()
                if container is not None:
                    label += str(container.index(parent) + 1)
        parts.append(label)
    return "-".join([owner, *reversed(parts)])


def resolve(node: etree._Element, folder: Path) -> None:
    for parent in node.iter():
        if "src" in parent.attrib:
            if len(parent) or (parent.text or "").strip():
                raise ProjectError(
                    "Image reference cannot be combined with inline data"
                )
            bitmap = read_bitmap(folder, dict(parent.attrib))
            parent.attrib.clear()
            etree.SubElement(parent, "obj_encoded").text = encode(bitmap)


def source_files(folder: Path) -> list[Path]:
    return [p for p in (folder / "images").rglob("*") if p.is_file()]


def stylesheet_assets(
    value: Any,
    folder: Path,
    *,
    exporting: bool,
    owner: str = "style",
    _writer: AssetWriter | None = None,
) -> Any:
    writer = _writer or (AssetWriter(folder) if exporting else None)
    if isinstance(value, list):
        return [
            stylesheet_assets(
                v, folder, exporting=exporting, owner=owner, _writer=writer
            )
            for v in value
        ]
    if not isinstance(value, dict):
        return value
    order = {k: v for k, v in value.items() if k in {"$order", "$before"}}
    fields = {k: v for k, v in value.items() if k not in order}
    old, new = ("obj_encoded", "src") if exporting else ("src", "obj_encoded")
    for key, annotation in order.items():
        if isinstance(annotation, list):
            order[key] = [new if v == old else v for v in annotation]
        elif isinstance(annotation, dict):
            order[key] = {
                new if k == old else k: new if v == old else v
                for k, v in annotation.items()
            }
    if (
        exporting
        and isinstance(fields.get("obj_encoded"), str)
        and fields["obj_encoded"].startswith("12:bitmapobject")
        and not is_empty(fields["obj_encoded"])
    ):
        if set(fields) != {"obj_encoded"}:
            raise ProjectError("Image reference cannot be combined with inline data")
        assert writer is not None
        return {**writer.export(fields["obj_encoded"], owner), **order}
    if not exporting and "src" in fields:
        return {"obj_encoded": encode(read_bitmap(folder, fields)), **order}
    return {
        k: stylesheet_assets(
            v, folder, exporting=exporting, owner=owner, _writer=writer
        )
        for k, v in value.items()
    }

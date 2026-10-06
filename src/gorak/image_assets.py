"""Application-local PNG assets with lossless native bitmap metadata."""

import json
import re
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


def metadata_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bitmap.json")


def png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", compress_level=9)
    return output.getvalue()


def project(bitmap: Bitmap) -> tuple[bytes, dict[str, Any]]:
    w, h = bitmap.width, bitmap.height
    size = w * h
    header = list(bitmap.header)
    palette = [list(map(int, header[i : i + 4])) for i in range(14, len(header), 4)]
    padding: list[int] = []
    if int(header[12]) == 2 and len(bitmap.pixels) == ((w + 7) // 8) * h:
        image = Image.frombytes("1", (w, h), bytes(v ^ 255 for v in bitmap.pixels))
        if w % 8:
            stride = (w + 7) // 8
            padding = [
                bitmap.pixels[(y + 1) * stride - 1] & ((1 << (8 - w % 8)) - 1)
                for y in range(h)
            ]
    elif len(bitmap.pixels) == size and palette:
        image = Image.frombytes("P", (w, h), bitmap.pixels)
        image.putpalette([c for entry in palette for c in entry[:3]])
    elif len(bitmap.pixels) == size * 3:
        image = Image.frombytes("RGB", (w, h), bitmap.pixels, "raw", "BGR")
    elif len(bitmap.pixels) == size * 4:
        image = Image.frombytes("RGBA", (w, h), bitmap.pixels, "raw", "BGRA")
    else:
        raise ProjectError("Unsupported bitmap pixel layout")
    meta: dict[str, Any] = {
        "version": 1,
        "mode": image.mode,
        "header": header[:14],
        "tail": list(bitmap.tail),
    }
    if any(any(entry) for entry in palette):
        meta["palette"] = palette
    if padding:
        meta["padding_bits"] = padding
    return png_bytes(image), meta


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


def read_bitmap(folder: Path, reference: str) -> Bitmap:
    path = asset_path(folder, reference)
    image = read_png(path)
    meta_path = metadata_path(path)
    if not meta_path.exists():
        # PNG-first source: embed original pixels without a native file loader.
        image = image.convert("RGBA")
        header = [
            "12:bitmapobject",
            "0",
            "1",
            "9",
            str(image.width * image.height * 4),
            f"{len(reference)}:{reference}",
            "0",
            "1",
            "2",
            "0",
            str(image.width),
            str(image.height),
            "4",
            "256",
        ] + ["0"] * 1024
        return Bitmap(
            tuple(header),
            image.tobytes("raw", "BGRA"),
            ("0", "0", "0", "0", "0", "-1", "3", "0", "0", "0", "-1:", "-1:"),
        )
    if meta_path.is_symlink():
        raise ProjectError("Symlinked bitmap metadata is unsupported")
    try:
        if meta_path.stat().st_size > 1024 * 1024:
            raise ProjectError("Bitmap metadata exceeds supported bounds")
        meta = json.loads(meta_path.read_text())
        if (
            not isinstance(meta, dict)
            or type(meta.get("version")) is not int
            or meta["version"] != 1
            or set(meta)
            - {
                "version",
                "mode",
                "header",
                "tail",
                "palette",
                "padding_bits",
                "mask",
            }
        ):
            raise ProjectError("Unsupported bitmap metadata")
        header = list(meta["header"])
        tail = tuple(meta["tail"])
        if (
            len(header) != 14
            or not all(isinstance(v, str) for v in header)
            or len(tail) != 12
            or not all(isinstance(v, str) for v in tail)
        ):
            raise ProjectError("Invalid bitmap metadata fields")
        if image.mode != meta["mode"]:
            raise ProjectError(
                "Image pixel mode changed; retain the exported PNG mode or explicitly remove native bitmap metadata"
            )
        w, h = image.size
        if int(tail[5]) >= 0 and "mask" not in meta:
            raise ProjectError("Missing native bitmap mask reference")
        if "mask" in meta and (w, h) != (int(header[10]), int(header[11])):
            raise ProjectError("Resize requires removing native bitmap mask metadata")
        if image.mode == "P" and "transparency" in image.info:
            raise ProjectError("Indexed transparency requires PNG-first conversion")
        header[10:12] = [str(w), str(h)]
        if not 0 <= int(header[13]) <= 256:
            raise ProjectError("Invalid bitmap palette size")
        palette = meta.get("palette", [[0, 0, 0, 0] for _ in range(int(header[13]))])
        if (
            not isinstance(palette, list)
            or len(palette) != int(header[13])
            or any(
                not isinstance(row, list)
                or len(row) != 4
                or any(type(v) is not int or not 0 <= v <= 255 for v in row)
                for row in palette
            )
        ):
            raise ProjectError("Bitmap palette length changed")
        if image.mode == "P":
            colors = image.getpalette()
            assert colors is not None
            if max(image.tobytes(), default=0) >= len(palette):
                raise ProjectError("PNG uses an index outside its native palette")
            palette = [
                colors[i * 3 : i * 3 + 3] + [entry[3]]
                for i, entry in enumerate(palette)
            ]
            pixels = image.tobytes()
        elif image.mode == "1":
            pixels_array = bytearray(v ^ 255 for v in image.tobytes())
            if w % 8:
                padding = meta.get("padding_bits", [0] * h)
                if len(padding) != h:
                    raise ProjectError(
                        "Monochrome height changed with retained padding"
                    )
                stride = (w + 7) // 8
                mask = (1 << (8 - w % 8)) - 1
                for y, v in enumerate(padding):
                    if type(v) is not int or not 0 <= v <= mask:
                        raise ProjectError("Invalid monochrome padding")
                    i = (y + 1) * stride - 1
                    pixels_array[i] = (pixels_array[i] & ~mask) | v
            pixels = bytes(pixels_array)
        elif image.mode in {"RGB", "RGBA"}:
            pixels = image.tobytes("raw", "BGR" if image.mode == "RGB" else "BGRA")
        else:
            raise ProjectError("Unsupported PNG mode")
        header.extend(str(c) for entry in palette for c in entry)
        header[4] = str(len(pixels))
        mask_bytes = None
        if "mask" in meta:
            mask_image = read_png(asset_path(folder, meta["mask"]))
            if mask_image.mode != "1":
                raise ProjectError("Bitmap mask must be monochrome PNG")
            mask_bytes = mask_image.tobytes()
        bitmap = Bitmap(tuple(header), pixels, tail, mask_bytes)
        # Validate retained fields and lengths through the same bounded reader.
        return decode(encode(bitmap))
    except (KeyError, TypeError, ValueError, IndexError, OSError) as ex:
        raise ProjectError(f"Invalid bitmap metadata {meta_path}: {ex}") from ex


def export_bitmap(folder: Path, text: str, fallback: str) -> str:
    bitmap = decode(text)
    data, meta = project(bitmap)
    origin = bitmap.origin
    base = (
        re.sub(
            r"[^A-Za-z0-9_.-]",
            "-",
            PureWindowsPath(origin).stem if origin else fallback,
        ).strip(".-")
        or "image"
    )
    base = base[:100]
    # Stable slot allocation: reuse matching named variants before choosing a
    # free suffix. Different original names are intentionally independent.
    directory = folder / "images"
    if directory.is_symlink():
        raise ProjectError("Symlinked image directory")
    directory.mkdir(parents=True, exist_ok=True)
    for candidate in sorted(directory.glob("*.png")):
        if candidate.is_symlink():
            raise ProjectError("Symlinked image asset")
        side = metadata_path(candidate)
        try:
            if side.is_file():
                old = json.loads(side.read_text())
                old_origin = old["header"][5].split(":", 1)[1]
            else:
                old_origin = candidate.relative_to(folder).as_posix()
            if old_origin != origin:
                continue
            if not origin and not re.fullmatch(
                re.escape(base) + r"(?:-\d+)?", candidate.stem
            ):
                continue
            restored = read_bitmap(folder, candidate.relative_to(folder).as_posix())
            # Original signifiers remain distinct, including their spelling.
            left = list(restored.header)
            right = list(bitmap.header)
            if (
                left == right
                and restored.pixels == bitmap.pixels
                and restored.tail == bitmap.tail
                and restored.mask == bitmap.mask
            ):
                return candidate.relative_to(folder).as_posix()
        except (OSError, ValueError, KeyError, TypeError, IndexError, ProjectError):
            continue  # Never overwrite an edited or invalid existing asset.
    index = 0
    while True:
        name = base + (f"-{index:02d}" if index else "") + ".png"
        path = directory / name
        occupied = {p.name.casefold() for p in directory.iterdir()}
        if not any(
            n.casefold() in occupied
            for n in (name, name + ".bitmap.json", path.stem + ".mask.png")
        ):
            break
        index += 1
    if bitmap.mask is not None:
        mask_path = path.with_name(path.stem + ".mask.png")
        # Preserve every bit, including alignment/unused bits, in a one-row mask.
        mask_image = Image.frombytes(
            "1", (max(1, len(bitmap.mask) * 8), 1), bitmap.mask or b"\0"
        )
        if not bitmap.mask:
            raise ProjectError("Empty native mask is unsupported")
        if mask_image.width > MAX_PIXELS:
            raise ProjectError("Native mask too large")
        mask_path.write_bytes(png_bytes(mask_image))
        meta["mask"] = mask_path.relative_to(folder).as_posix()
    path.write_bytes(data)
    metadata_path(path).write_text(json.dumps(meta, indent=2) + "\n")
    return path.relative_to(folder).as_posix()


def externalize(node: etree._Element, folder: Path, owner: str) -> etree._Element:
    result = deepcopy(node)
    for encoded in result.iter("obj_encoded"):
        if any(parent.tag == "fielddefaults" for parent in encoded.iterancestors()):
            continue  # Export only stylesheet overrides, after inheritance.
        if not (encoded.text or "").startswith("12:bitmapobject"):
            continue  # Other serialized objects retain the existing inline path.
        if is_empty(encoded.text or ""):
            continue
        ref = export_bitmap(folder, encoded.text or "", asset_label(encoded, owner))
        encoded.tag = "src"
        encoded.text = ref
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
    for source in list(node.iter("src")):
        parent = source.getparent()
        if parent is None or len(parent) != 1 or source.attrib:
            raise ProjectError("Image reference cannot be combined with inline data")
        source.tag = "obj_encoded"
        source.text = encode(read_bitmap(folder, source.text or ""))
    for parent in node.iter():
        if "src" in parent.attrib:
            if (
                len(parent)
                or (parent.text or "").strip()
                or set(parent.attrib) != {"src"}
            ):
                raise ProjectError(
                    "Image reference cannot be combined with inline data"
                )
            ref = parent.attrib.pop("src")
            etree.SubElement(parent, "obj_encoded").text = encode(
                read_bitmap(folder, ref)
            )


def source_files(folder: Path) -> list[Path]:
    return [p for p in (folder / "images").rglob("*") if p.is_file()] + list(
        folder.glob("*.icons.json")
    )


def stylesheet_assets(
    value: Any, folder: Path, *, exporting: bool, owner: str = "style"
) -> Any:
    """Translate bitmap properties after computing stylesheet inheritance."""
    if isinstance(value, list):
        return [
            stylesheet_assets(v, folder, exporting=exporting, owner=owner)
            for v in value
        ]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if (
            exporting
            and key == "obj_encoded"
            and isinstance(item, str)
            and item.startswith("12:bitmapobject")
            and not is_empty(item)
        ):
            result["src"] = export_bitmap(folder, item, owner)
        elif not exporting and key == "src":
            if "obj_encoded" in value:
                raise ProjectError(
                    "Image reference cannot be combined with inline data"
                )
            result["obj_encoded"] = encode(read_bitmap(folder, item))
        else:
            result[key] = stylesheet_assets(
                item, folder, exporting=exporting, owner=owner
            )
    for key in ("$order", "$before"):
        if key in result:
            # Native property-order annotations name the translated property.
            old, new = ("obj_encoded", "src") if exporting else ("src", "obj_encoded")
            if isinstance(result[key], list):
                result[key] = [new if v == old else v for v in result[key]]
            elif isinstance(result[key], dict):
                result[key] = {
                    new if k == old else k: new if v == old else v
                    for k, v in result[key].items()
                }
    return result

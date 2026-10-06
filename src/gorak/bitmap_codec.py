"""Bounded decoding of observed native BitmapObject pixel and mask buffers."""

import re
from dataclasses import dataclass

from .errors import ProjectError

MAX_BYTES = 128 * 1024 * 1024
MAX_PIXELS = 32 * 1024 * 1024


@dataclass(frozen=True)
class Bitmap:
    header: tuple[str, ...]
    pixels: bytes
    tail: tuple[str, ...]
    mask: bytes | None = None

    @property
    def width(self) -> int:
        return int(self.header[10])

    @property
    def height(self) -> int:
        return int(self.header[11])

    @property
    def origin(self) -> str:
        return self.header[5].split(":", 1)[1]


def decode_buffer(text: str, offset: int, size: int) -> tuple[bytes, int]:
    if not 0 <= size <= MAX_BYTES:
        raise ProjectError("Bitmap buffer exceeds supported bounds")
    result = bytearray()

    def take(count: int) -> str:
        nonlocal offset
        value = ""
        while len(value) < count:
            if offset >= len(text):
                raise ProjectError("Truncated bitmap buffer")
            c = text[offset]
            offset += 1
            if c in "\r\n":
                continue
            if c not in "0123456789abcdefABCDEF":
                raise ProjectError("Invalid bitmap buffer token")
            value += c
        return value

    while len(result) < size:
        while offset < len(text) and text[offset] in "\r\n":
            offset += 1
        if offset >= len(text):
            raise ProjectError("Truncated bitmap buffer")
        token = text[offset]
        count = 1
        if token in "rR":
            offset += 1
            number = int(take(1), 16)
            if token == "r":
                count = number + 3
            else:
                if not 1 <= number <= 4:
                    raise ProjectError("Unsupported bitmap run width")
                count = int.from_bytes(bytes.fromhex(take(number * 2)), "little")
                # Native single-byte 00 denotes 256, observed in real exports.
                if count == 0:
                    if number != 1:
                        raise ProjectError("Unsupported zero bitmap run")
                    count = 256
        value = int(take(2), 16)
        if len(result) + count > size:
            raise ProjectError("Bitmap run exceeds declared buffer length")
        result.extend(bytes([value]) * count)
    return bytes(result), offset


def encode_buffer(data: bytes) -> str:
    tokens = []
    i = 0
    while i < len(data):
        end = i + 1
        while end < len(data) and data[end] == data[i]:
            end += 1
        count = end - i
        if count < 3:
            tokens.append(data[i:end].hex())
        elif count <= 18:
            tokens.append(f"r{count - 3:x}{data[i]:02x}")
        else:
            size = max(1, (count.bit_length() + 7) // 8)
            tokens.append(
                f"R{size:x}{count.to_bytes(size, 'little').hex()}{data[i]:02x}"
            )
        i = end
    text = "".join(tokens)
    return "\n".join(text[i : i + 64] for i in range(0, len(text), 64))


def decode(text: str) -> Bitmap:
    if len(text) > MAX_BYTES * 3:
        raise ProjectError("Bitmap text exceeds supported bounds")
    # WML from older exports flattened line breaks into spaces. Native objects
    # need their length-prefixed string, so only unambiguous native text is read.
    lines = text.replace("\r\n", "\n").splitlines(keepends=True)
    try:
        if len(lines) < 15 or lines[0].strip() != "12:bitmapobject":
            raise ProjectError("Unsupported embedded bitmap serialization")
        header = [s.rstrip("\n") for s in lines[:14]]
        if not re.fullmatch(r"-?\d+:.*", header[5]):
            raise ProjectError("Invalid bitmap filename")
        length, filename = header[5].split(":", 1)
        if int(length) != len(filename) and not (length == "-1" and not filename):
            raise ProjectError("Unsupported bitmap filename length")
        width, height, flags, palette = map(int, header[10:14])
        if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
            raise ProjectError("Bitmap dimensions exceed supported bounds")
        if flags not in {2, 4, 12} or not 0 <= palette <= 256:
            raise ProjectError("Unsupported bitmap format or palette")
        end = 14 + palette * 4
        header.extend(s.rstrip("\n") for s in lines[14:end])
        if len(header) != end:
            raise ProjectError("Truncated bitmap palette")
        if any(not 0 <= int(v) <= 255 for v in header[14:]):
            raise ProjectError("Unsupported bitmap palette value")
        size = int(lines[end])
        if size != int(header[4]):
            raise ProjectError("Bitmap length fields disagree")
        offset = sum(map(len, lines[: end + 1]))
        normalized = "".join(lines)
        pixels, offset = decode_buffer(normalized, offset, size)
        rest = normalized[offset:].lstrip("\n")
        parts = rest.splitlines(keepends=True)
        if len(parts) < 12:
            raise ProjectError("Truncated bitmap metadata")
        tail = [p.rstrip("\n") for p in parts[:6]]
        mask_size = int(tail[5])
        mask = None
        if mask_size >= 0:
            mask, position = decode_buffer(rest, sum(map(len, parts[:6])), mask_size)
            tail.extend(rest[position:].lstrip("\n").splitlines())
        elif mask_size == -1:
            tail.extend(p.rstrip("\n") for p in parts[6:])
        else:
            raise ProjectError("Unsupported bitmap mask length")
        if len(tail) != 12 or tail[-2:] != ["-1:", "-1:"]:
            raise ProjectError("Unsupported additional bitmap data")
        for value in tail[:10]:
            int(value)
        return Bitmap(tuple(header), pixels, tuple(tail), mask)
    except (ValueError, IndexError) as ex:
        raise ProjectError(f"Invalid embedded bitmap: {ex}") from ex


def encode(bitmap: Bitmap) -> str:
    header = list(bitmap.header)
    header[4] = str(len(bitmap.pixels))
    tail = list(bitmap.tail)
    if bitmap.mask is not None:
        tail[5] = str(len(bitmap.mask))
        tail.insert(6, encode_buffer(bitmap.mask))
    else:
        tail[5] = "-1"
    return (
        "\n".join(
            [*header, str(len(bitmap.pixels)), encode_buffer(bitmap.pixels), *tail]
        )
        + "\n"
    )


def normalized(text: str) -> str:
    """Canonicalize known transport runs without changing unknown inline objects."""
    if not text.startswith("12:bitmapobject"):
        return text
    try:
        return encode(decode(text))
    except ProjectError:
        return text


def is_empty(text: str) -> bool:
    """Recognize the native unloaded bitmap placeholder (no pixel buffer)."""
    lines = text.splitlines()
    return (
        len(lines) == 22
        and lines[:5] == ["12:bitmapobject", "0", "1", "9", "0"]
        and lines[5] == "-1:"
        and lines[6:]
        == [
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

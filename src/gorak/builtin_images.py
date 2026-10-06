"""Stable packaged image identities shared by exporters and source consumers."""

import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from pathlib import PureWindowsPath

from .errors import ProjectError


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict[str, str | list[str]]]:
    result: dict[str, dict[str, str | list[str]]] = json.loads(
        files("gorak.templates").joinpath("builtin_images.json").read_text()
    )
    return result


def entry(reference: str) -> dict[str, str | list[str]]:
    name = reference.removeprefix("builtin:")
    if not reference.startswith("builtin:") or name not in catalog():
        raise ProjectError(f"Unknown built-in image: {reference}")
    return catalog()[name]


@lru_cache(maxsize=32)
def image_bytes(reference: str) -> bytes:
    item = entry(reference)
    data = files("gorak.templates").joinpath("images", str(item["file"])).read_bytes()
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ProjectError(f"Built-in image checksum mismatch: {reference}")
    return data


def match(data: bytes, origin: str) -> str | None:
    digest = hashlib.sha256(data).hexdigest()
    for name, item in catalog().items():
        reference = "builtin:" + name
        # A developer's differently named copy remains an independent asset.
        if digest == item["sha256"] and (
            origin == reference or PureWindowsPath(origin).name in item["names"]
        ):
            return reference
    return None

"""Read the single public release stream and verify executable downloads."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .errors import ProjectError

REPOSITORY = "dougwhite/gorak"
RELEASES = f"https://github.com/{REPOSITORY}/releases"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_BINARY_BYTES = 256 * 1024 * 1024


def read_json_url(url: str) -> dict[str, Any]:
    request = Request(
        url, headers={"User-Agent": "gorak-updater", "Accept": "application/json"}
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError("release metadata is too large")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("release metadata must be an object")
        return value
    except (URLError, OSError, ValueError) as error:
        raise ProjectError(f"Cannot read gorak release metadata: {error}") from error


def release_url(tag: str, name: str) -> str:
    if not re.fullmatch(r"v[0-9][A-Za-z0-9.+-]*", tag):
        raise ProjectError("Invalid gorak release tag")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise ProjectError("Invalid gorak release asset name")
    return f"{RELEASES}/download/{tag}/{name}"


def latest_release(target: str) -> tuple[str, dict[str, str]]:
    release = read_json_url(API)
    tag = release.get("tag_name")
    if release.get("draft") is not False or not isinstance(tag, str):
        raise ProjectError("No published gorak binary release is available")
    manifest = read_json_url(release_url(tag, "gorak-release.json"))
    if manifest.get("schema") != 1 or manifest.get("tag") != tag:
        raise ProjectError("Unsupported or mismatched gorak release manifest")
    assets = manifest.get("assets")
    asset = assets.get(target) if isinstance(assets, dict) else None
    expected = f"gorak-{target}" + (".exe" if target.startswith("windows-") else "")
    if (
        not isinstance(asset, dict)
        or asset.get("name") != expected
        or not isinstance(asset.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])
        or not isinstance(manifest.get("version"), str)
    ):
        raise ProjectError(f"Release {tag} has no valid executable for {target}")
    return tag, {
        "name": expected,
        "sha256": asset["sha256"],
        "version": manifest["version"],
    }


def download_binary(tag: str, asset: dict[str, str], destination: Path) -> None:
    request = Request(
        release_url(tag, asset["name"]), headers={"User-Agent": "gorak-updater"}
    )
    digest = hashlib.sha256()
    created = False
    try:
        with destination.open("xb") as output:
            created = True
            size = 0
            with urlopen(request, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BINARY_BYTES:
                        raise ProjectError("gorak download exceeds the size limit")
                    digest.update(chunk)
                    output.write(chunk)
        if size == 0 or digest.hexdigest() != asset["sha256"]:
            raise ProjectError(
                "gorak download checksum mismatch; installation unchanged"
            )
        destination.chmod(0o700)
    except (URLError, OSError, ProjectError) as error:
        if created:
            destination.unlink(missing_ok=True)
        raise ProjectError(f"Cannot download gorak: {error}") from error

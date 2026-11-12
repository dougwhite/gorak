"""Build a single-file artifact on its target OS; never publish anything."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from release_version import version_tag

from gorak.build_info import platform_id


def release_tag(package_version: str, tag: str | None, release: bool) -> str:
    try:
        canonical = version_tag(package_version)
    except ValueError as error:
        raise ValueError(
            "Release tag requires a non-development package version"
        ) from error
    selected = tag or canonical
    if not re.fullmatch(r"v[0-9][A-Za-z0-9.+-]*", selected):
        raise ValueError(
            "tag must start with v and a digit and contain only version characters"
        )
    if release and tag != canonical:
        raise ValueError(f"Release tag must equal {canonical}")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release", action="store_true", help="Require a matching explicit release tag"
    )
    parser.add_argument(
        "--tag",
        default=os.environ.get("GORAK_BUILD_TAG") or None,
        help="Release tag (defaults to the repository's version-to-tag convention)",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    package_version = version("gorak")
    try:
        tag = release_tag(package_version, args.tag, args.release)
    except ValueError as error:
        parser.error(str(error))
    target = platform_id()
    name = f"gorak-{target}"
    work = root / "build" / "binary" / target
    work.mkdir(parents=True, exist_ok=True)
    info = work / "binary-build.json"
    info.write_text(
        json.dumps({"version": package_version, "tag": tag, "platform": target}),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(root / "dist" / "binary"),
        "--workpath",
        str(work / "work"),
        str(root / "scripts" / "gorak.spec"),
    ]
    subprocess.run(
        command,
        cwd=root,
        check=True,
        env={**os.environ, "GORAK_BINARY_WORK": str(work)},
    )
    artifact = (
        root
        / "dist"
        / "binary"
        / (name + (".exe" if target.startswith("windows") else ""))
    )
    with artifact.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {
        "schema": 1,
        "tag": tag,
        "version": package_version,
        "assets": {target: {"name": artifact.name, "sha256": digest}},
    }
    artifact.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(f"Built {artifact} ({artifact.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

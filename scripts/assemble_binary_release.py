"""Assemble locally built release files without uploading or creating a tag."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def assemble(directory: Path, allow_partial: bool = False) -> None:
    manifests = sorted(directory.glob("*.manifest.json"))
    if not manifests:
        raise ValueError("No platform manifests found")
    result: dict = {"schema": 1, "assets": {}}
    for path in manifests:
        manifest = json.loads(path.read_text())
        for key in ("tag", "version"):
            if key in result and result[key] != manifest[key]:
                raise ValueError(f"Platform manifests disagree on {key}")
            result[key] = manifest[key]
        for target, asset in manifest["assets"].items():
            if target in result["assets"] or Path(asset["name"]).name != asset["name"]:
                raise ValueError("Duplicate platform or invalid asset name")
            with (directory / asset["name"]).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != asset["sha256"]:
                    raise ValueError("Executable does not match its build manifest")
            result["assets"][target] = asset
    if not allow_partial and set(result["assets"]) != {"linux-x64", "windows-x64"}:
        raise ValueError("A release requires both Linux x64 and Windows x64 artifacts")
    (directory / "gorak-release.json").write_text(json.dumps(result, indent=2) + "\n")
    for name in ("install.sh", "install.ps1"):
        shutil.copyfile(Path(__file__).with_name(name), directory / name)
    names = [asset["name"] for asset in result["assets"].values()]
    names.extend(["gorak-release.json", "install.sh", "install.ps1"])
    sums = []
    for name in sorted(names):
        with (directory / name).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        sums.append(f"{digest}  {name}\n")
    (directory / "SHA256SUMS").write_text("".join(sums))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--allow-partial", action="store_true", help="Local testing only"
    )
    args = parser.parse_args()
    assemble(args.directory, args.allow_partial)

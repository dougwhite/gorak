import hashlib
import json
from pathlib import Path

import pytest
from assemble_binary_release import assemble
from build_binary import release_tag


@pytest.mark.parametrize(
    ("version", "tag"),
    [
        ("1.2.3", "v1.2.3"),
        ("0.1.0a1", "v0.1.0-alpha.1"),
        ("1.2.3b2", "v1.2.3-beta.2"),
        ("1.2.3rc3", "v1.2.3-rc.3"),
    ],
)
def test_release_tag_matches_package_including_alpha(version: str, tag: str) -> None:
    assert release_tag(version, tag, True) == tag
    assert release_tag(version, None, False) == tag


@pytest.mark.parametrize(
    ("version", "tag"),
    [
        ("1.2.3", None),
        ("1.2.3", "v1.2.4"),
        ("0.1.0a1", "v0.1.0-alpha.1.dev.42"),
        ("0.1.0a1", "v0.1.0a1"),
        ("1.2.3.dev1", "v1.2.3.dev1"),
    ],
)
def test_release_refuses_missing_mismatched_or_development_tag(
    version: str, tag: str | None
) -> None:
    with pytest.raises(ValueError, match="Release tag"):
        release_tag(version, tag, True)


def test_review_build_allows_local_tag_but_not_unsafe_characters() -> None:
    assert release_tag("1.2.3", None, False) == "v1.2.3"
    assert release_tag("1.2.3", "v1.2.3-local-proof", False) == "v1.2.3-local-proof"
    with pytest.raises(ValueError, match="version characters"):
        release_tag("1.2.3", "v1.2.3/unsafe", False)


def artifact(directory: Path, target: str, tag: str = "v1") -> None:
    name = f"gorak-{target}" + (".exe" if target.startswith("windows-") else "")
    data = b"synthetic artifact " + target.encode()
    (directory / name).write_bytes(data)
    (directory / f"{target}.manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "tag": tag,
                "version": "1",
                "assets": {
                    target: {"name": name, "sha256": hashlib.sha256(data).hexdigest()}
                },
            }
        )
    )


def test_release_requires_both_platforms(tmp_path: Path) -> None:
    artifact(tmp_path, "linux-x64")
    with pytest.raises(ValueError, match="both Linux"):
        assemble(tmp_path)
    assert not (tmp_path / "gorak-release.json").exists()
    artifact(tmp_path, "windows-x64")
    assemble(tmp_path)
    manifest = json.loads((tmp_path / "gorak-release.json").read_text())
    assert set(manifest["assets"]) == {"linux-x64", "windows-x64"}
    assert "install.ps1" in (tmp_path / "SHA256SUMS").read_text()


def test_release_refuses_mismatched_builds_or_tampering(tmp_path: Path) -> None:
    artifact(tmp_path, "linux-x64")
    artifact(tmp_path, "windows-x64", "v2")
    with pytest.raises(ValueError, match="disagree"):
        assemble(tmp_path)
    artifact(tmp_path, "windows-x64")
    (tmp_path / "gorak-linux-x64").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="does not match"):
        assemble(tmp_path)

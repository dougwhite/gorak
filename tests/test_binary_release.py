import hashlib
import io
import json
from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest

from gorak import binary_release as release
from gorak.errors import ProjectError


def metadata(monkeypatch: pytest.MonkeyPatch, manifest: dict[str, Any]) -> None:
    def read(url: str) -> dict[str, Any]:
        if url == release.API:
            return {"tag_name": "v0.1.0a1", "draft": False}
        assert url == release.release_url("v0.1.0a1", "gorak-release.json")
        return manifest

    monkeypatch.setattr(release, "read_json_url", read)


def manifest() -> dict[str, Any]:
    return {
        "schema": 1,
        "tag": "v0.1.0a1",
        "version": "0.1.0a1",
        "assets": {"linux-x64": {"name": "gorak-linux-x64", "sha256": "a" * 64}},
    }


def test_alpha_version_uses_the_same_published_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata(monkeypatch, manifest())
    tag, asset = release.latest_release("linux-x64")
    assert tag == "v0.1.0a1"
    assert asset["version"] == "0.1.0a1"


@pytest.mark.parametrize(
    "change",
    [
        {"tag": "v2"},
        {"schema": 2},
        {"assets": {}},
        {"assets": {"linux-x64": {"name": "../gorak", "sha256": "a" * 64}}},
        {"assets": {"linux-x64": {"name": "gorak-linux-x64", "sha256": "bad"}}},
    ],
)
def test_reject_incompatible_or_incomplete_release(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    metadata(monkeypatch, {**manifest(), **change})
    with pytest.raises(ProjectError):
        release.latest_release("linux-x64")


@pytest.mark.parametrize(
    "tag,name", [("../v1", "gorak"), ("v1", "../gorak"), ("v1?other", "gorak")]
)
def test_release_locations_are_fixed(tag: str, name: str) -> None:
    with pytest.raises(ProjectError):
        release.release_url(tag, name)


def test_download_checks_hash_and_cleans_partial_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"synthetic executable"
    monkeypatch.setattr(release, "urlopen", lambda *a, **k: io.BytesIO(data))
    path = tmp_path / "candidate"
    asset = {"name": "gorak-linux-x64", "sha256": hashlib.sha256(data).hexdigest()}
    release.download_binary("v1", asset, path)
    assert path.read_bytes() == data
    path.unlink()
    with pytest.raises(ProjectError, match="checksum"):
        release.download_binary("v1", {**asset, "sha256": "0" * 64}, path)
    assert not path.exists()
    monkeypatch.setattr(release, "MAX_BINARY_BYTES", 2)
    with pytest.raises(ProjectError, match="size limit"):
        release.download_binary("v1", asset, path)
    assert not path.exists()


def test_metadata_network_error_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise URLError("offline")

    monkeypatch.setattr(release, "urlopen", fail)
    with pytest.raises(ProjectError, match="metadata.*offline"):
        release.read_json_url(release.API)


@pytest.mark.parametrize(
    "payload",
    [b"[]", b"not json", b"x" * (1024 * 1024 + 1)],
    ids=["array", "invalid-json", "oversized"],
)
def test_metadata_bounds_and_shape(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    monkeypatch.setattr(release, "urlopen", lambda *a, **k: io.BytesIO(payload))
    with pytest.raises(ProjectError):
        release.read_json_url(release.API)


def test_metadata_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        release, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(manifest()).encode())
    )
    assert release.read_json_url(release.API) == manifest()


def test_download_never_removes_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "existing"
    path.write_text("keep")
    with pytest.raises(ProjectError):
        release.download_binary(
            "v1", {"name": "gorak-linux-x64", "sha256": "a" * 64}, path
        )
    assert path.read_text() == "keep"

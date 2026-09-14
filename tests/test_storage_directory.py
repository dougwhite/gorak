import hashlib
import json
from pathlib import Path

import pytest

from gorak.encoded_graph import UnsupportedSource
from gorak.storage_directory import read_directory, write_directory
from tests.test_storage_archive import archive


def test_partitioned_archive_needs_only_tracked_files(tmp_path: Path) -> None:
    source = archive()
    directory = tmp_path / "export"
    write_directory(source, directory)
    assert read_directory(directory).dumps() == source.dumps()
    assert sorted(p.suffix for p in (directory / "objects").iterdir()) == [
        ".srcobj",
        ".srcobj",
    ]
    assert not list(directory.rglob("*.xml"))
    assert not (directory / ".openroad").exists()


def test_rejects_modified_or_missing_payload(tmp_path: Path) -> None:
    directory = tmp_path / "export"
    write_directory(archive(), directory)
    path = next((directory / "objects").iterdir())
    path.write_text(path.read_text().replace("$", "!", 1))
    with pytest.raises(UnsupportedSource):
        read_directory(directory)
    path.unlink()
    with pytest.raises(UnsupportedSource):
        read_directory(directory)


def test_never_replaces_existing_directory_or_file(tmp_path: Path) -> None:
    directory = tmp_path / "export"
    directory.mkdir()
    (directory / "keep.txt").write_text("local work")
    with pytest.raises(UnsupportedSource):
        write_directory(archive(), directory)
    assert (directory / "keep.txt").read_text() == "local work"
    with pytest.raises(UnsupportedSource):
        write_directory(archive(), directory / "keep.txt")


def test_unknown_files_and_symlinks_are_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "export"
    write_directory(archive(), directory)
    extra = directory / "unrecognized.txt"
    extra.write_text("not ignored")
    with pytest.raises(UnsupportedSource):
        read_directory(directory)
    extra.unlink()
    extra.symlink_to(tmp_path)
    with pytest.raises(UnsupportedSource):
        read_directory(directory)


@pytest.mark.parametrize("change", ["duplicate", "traversal", "sizes", "format"])
def test_rejects_tampered_manifest(tmp_path: Path, change: str) -> None:
    directory = tmp_path / "export"
    write_directory(archive(), directory)
    path = directory / "manifest.json"
    data = json.loads(path.read_text())
    if change == "duplicate":
        data["objects"].append(data["objects"][0])
    elif change == "traversal":
        data["objects"][0]["identity"] = "../../outside"
    elif change == "sizes":
        data["objects"][0]["sizes"] = [1]
    else:
        data["format"] = True
    path.write_text(json.dumps(data))
    (directory / "manifest.sha256").write_text(
        hashlib.sha256(path.read_bytes()).hexdigest() + "\n"
    )
    with pytest.raises(UnsupportedSource):
        read_directory(directory)


def test_row_order_does_not_change_archive_identity(tmp_path: Path) -> None:
    source = archive()
    expected = source.dumps()
    for rows in source.tables.values():
        rows.reverse()
    assert source.dumps() == expected
    write_directory(source, tmp_path / "export")
    assert read_directory(tmp_path / "export").dumps() == expected


def test_git_metadata_is_not_source(tmp_path: Path) -> None:
    directory = tmp_path / "export"
    write_directory(archive(), directory)
    (directory / ".git").mkdir()
    (directory / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    assert read_directory(directory).dumps() == archive().dumps()


@pytest.mark.parametrize("name", ["manifest.json", "manifest.sha256", ".gitattributes"])
def test_rejects_metadata_damage(tmp_path: Path, name: str) -> None:
    directory = tmp_path / "export"
    write_directory(archive(), directory)
    path = directory / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(UnsupportedSource, match="hash_or_attributes"):
        read_directory(directory)

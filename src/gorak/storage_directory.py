"""Partitioned, hash-checked native source archives for fresh-clone experiments."""

import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from tempfile import mkdtemp

from .encoded_graph import UnsupportedSource
from .storage_archive import MAX_ARCHIVE, Archive, Row, loads
from .storage_graph import decode, encode

ATTRIBUTES = (
    b"objects/*.srcobj -text\nmanifest.json -text\nmanifest.sha256 -text\n"
    b".gitattributes text eol=lf\n"
)


def write_directory(archive: Archive, destination: Path) -> None:
    """Publish an entirely new directory; never overwrite a checkout or source file."""
    archive.validate()
    if destination.exists() or destination.is_symlink():
        raise UnsupportedSource("archive_destination_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(mkdtemp(prefix=".gorak-storage-", dir=destination.parent))
    try:
        (staging / "objects").mkdir()
        grouped: dict[int, list[Row]] = defaultdict(list)
        for row in archive.tables["ii_srcobj_encoded"]:
            identity = row["entity_id"]
            assert isinstance(identity, int)
            grouped[identity].append(row)
        entries = []
        for identity, rows in sorted(grouped.items()):
            ordered = sorted(rows, key=lambda r: int(str(r["sequence_no"])))
            payload = "".join(str(row["text_string"]) for row in ordered)
            data = encode(decode(payload)).encode("ascii")
            name = f"objects/{identity}.srcobj"
            (staging / name).write_bytes(data)
            entries.append(
                {
                    "identity": identity,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "sizes": [len(str(r["text_string"])) for r in ordered],
                }
            )
        tables = dict(archive.tables)
        tables["ii_srcobj_encoded"] = []
        manifest = (
            json.dumps(
                {"format": 1, "tables": tables, "objects": entries},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("ascii")
        (staging / "manifest.json").write_bytes(manifest)
        (staging / "manifest.sha256").write_bytes(
            hashlib.sha256(manifest).hexdigest().encode("ascii") + b"\n"
        )
        (staging / ".gitattributes").write_bytes(ATTRIBUTES)
        # Re-read what will actually survive a git clone before publication.
        restored = read_directory(staging)
        if restored.dumps() != archive.dumps():
            raise UnsupportedSource("archive_directory_verification_failed")
        if destination.exists() or destination.is_symlink():
            raise UnsupportedSource("archive_destination_exists")
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def read_directory(directory: Path) -> Archive:
    """Reject corruption, symlinks and extra files rather than silently losing source."""
    if directory.is_symlink() or not directory.is_dir():
        raise UnsupportedSource("invalid_archive_directory")
    paths = [
        path
        for path in directory.rglob("*")
        if path.relative_to(directory).parts[0] != ".git"
    ]
    if any(path.is_symlink() for path in paths):
        raise UnsupportedSource("archive_symlink_not_supported")
    files = {p.relative_to(directory).as_posix(): p for p in paths if p.is_file()}
    if sum(p.stat().st_size for p in files.values()) > MAX_ARCHIVE:
        raise UnsupportedSource("archive_size_budget_exceeded")
    if not {"manifest.json", "manifest.sha256", ".gitattributes"} <= files.keys():
        raise UnsupportedSource("missing_archive_manifest")
    manifest = files["manifest.json"].read_bytes()
    if (
        files["manifest.sha256"].read_bytes()
        != (hashlib.sha256(manifest).hexdigest().encode("ascii") + b"\n")
        or files[".gitattributes"].read_bytes() != ATTRIBUTES
    ):
        raise UnsupportedSource("archive_manifest_hash_or_attributes_mismatch")
    from .storage_archive import _unique_object

    try:
        raw = json.loads(manifest, object_pairs_hook=_unique_object)
        if (
            not isinstance(raw, dict)
            or set(raw) != {"format", "tables", "objects"}
            or type(raw["format"]) is not int
            or raw["format"] != 1
        ):
            raise UnsupportedSource("invalid_archive_manifest")
        tables = raw["tables"]
        if (
            not isinstance(tables, dict)
            or tables.get("ii_srcobj_encoded") != []
            or not isinstance(raw["objects"], list)
        ):
            raise UnsupportedSource("invalid_archive_manifest")
        expected = {"manifest.json", "manifest.sha256", ".gitattributes"}
        for entry in raw["objects"]:
            if not isinstance(entry, dict) or set(entry) != {
                "identity",
                "sha256",
                "sizes",
            }:
                raise UnsupportedSource("invalid_archive_object_entry")
            identity = entry["identity"]
            if type(identity) is not int or not 1 <= identity < 2**31:
                raise UnsupportedSource("invalid_archive_object_identity")
            name = f"objects/{identity}.srcobj"
            if name in expected or name not in files:
                raise UnsupportedSource("missing_or_duplicate_archive_object")
            expected.add(name)
            data = files[name].read_bytes()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise UnsupportedSource("archive_object_hash_mismatch")
            sizes = entry["sizes"]
            if (
                not isinstance(sizes, list)
                or not sizes
                or any(type(n) is not int or not 1 <= n <= 1790 for n in sizes)
                or sum(sizes) != len(data)
            ):
                raise UnsupportedSource("invalid_archive_chunk_sizes")
            offset = 0
            for sequence, size in enumerate(sizes):
                tables["ii_srcobj_encoded"].append(
                    {
                        "entity_id": identity,
                        "sub_type": 1,
                        "sequence_no": sequence,
                        "text_string": data[offset : offset + size].decode("ascii"),
                    }
                )
                offset += size
        if set(files) != expected:
            raise UnsupportedSource("unrecognized_archive_files")
        return loads(json.dumps({"format": 1, "tables": tables}))
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise UnsupportedSource("invalid_archive_directory_data") from exc

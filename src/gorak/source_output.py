"""Write projected source and optionally retain the digest of the bytes written."""

import hashlib
import os
from pathlib import Path


def write_text(
    path: Path,
    text: str,
    *,
    newline: str | None = None,
    digests: dict[Path, str] | None = None,
) -> None:
    data = text.replace("\n", os.linesep if newline is None else newline).encode(
        "utf-8"
    )
    path.write_bytes(data)
    if digests is not None:
        digests[path] = hashlib.sha256(data).hexdigest()

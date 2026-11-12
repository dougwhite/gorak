"""Atomically publish small JSON records for supporting commands."""

import json
import os
from pathlib import Path
from uuid import uuid4


def write_record(path: Path, value: object) -> None:
    staged = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        with staged.open("w") as handle:
            handle.write(json.dumps(value, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)

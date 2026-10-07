"""Explicit provenance for accepted submissions used as local tracking baselines."""

import hashlib
import json
from pathlib import Path


def accepted_baseline(
    target: Path, submitted: Path, operation: Path
) -> dict[Path, bytes]:
    """Stage the exact accepted XML and its receipt in the same file transaction.

    The digest ties the receipt to this cache version. A later native export can
    replace the XML; a receipt whose digest no longer matches is historical only.
    """
    content = submitted.read_bytes()
    receipt = {
        "origin": "accepted-submission",
        "sha256": hashlib.sha256(content).hexdigest(),
        "operation": str(operation),
        "native_reexport": False,
    }
    return {
        target: content,
        target.with_suffix(".receipt.json"): (
            json.dumps(receipt, indent=2) + "\n"
        ).encode(),
    }


def is_accepted_baseline(path: Path) -> bool:
    """A stale receipt never changes the comparison policy for a newer export."""
    try:
        receipt = json.loads(path.with_suffix(".receipt.json").read_text())
        return (
            isinstance(receipt, dict)
            and receipt.get("origin") == "accepted-submission"
            and receipt.get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest()
        )
    except (OSError, ValueError):
        return False

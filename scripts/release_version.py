"""The repository's Python-version to release-tag convention."""

import re


def version_tag(version: str) -> str:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:(a|b|rc)(\d+))?", version)
    if not match:
        raise ValueError("Expected a package release version")
    suffix = {"a": "alpha", "b": "beta", "rc": "rc"}.get(match[2])
    return f"v{match[1]}" + (f"-{suffix}.{match[3]}" if suffix else "")

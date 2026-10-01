"""Move compact-source defaults without reconstructing unrelated source or layout."""

import json
import re
import tomllib
from pathlib import Path

import tomlkit

from .component_defaults import (
    defaults_path,
    minimal_component_defaults,
    read_component_defaults,
)
from .errors import ProjectError


def stage_defaults_migration(root: Path, stage: Path) -> dict[Path, bytes | None]:
    """Preserve script bytes and all other TOML values; verify effective defaults."""
    changes: dict[Path, bytes | None] = {}
    for manifest in sorted(root.glob("*/app.json")):
        if manifest.parent.name.startswith("."):
            continue
        for source in sorted(manifest.parent.glob("*.w4gl")):
            original = source.read_bytes()
            separator = re.search(rb"(?m)^[ \t]*===[ \t]*(?:\r?\n|$)", original)
            header = original[: separator.start()] if separator else original
            tail = original[separator.start() :] if separator else b""
            metadata = tomllib.loads(header.decode("utf-8"))
            if "source_format" in metadata:
                raise ProjectError(
                    f"Defaults-only migration requires compact source: {source}"
                )
            sidecar = defaults_path(source)
            if "fielddefaults" not in metadata and not sidecar.exists():
                continue
            overrides = read_component_defaults(
                source, metadata.get("fielddefaults", {})
            )
            # This minimizer verifies that applying the new delta reconstructs
            # exactly the same effective defaults as the original override.
            delta = minimal_component_defaults(source, overrides)
            replacement = original
            if "fielddefaults" in metadata:
                metadata.pop("fielddefaults")
                encoded = tomlkit.dumps(metadata)
                if tomllib.loads(encoded) != metadata:
                    raise ProjectError(
                        f"Source metadata changed during migration: {source}"
                    )
                replacement = encoded.encode("utf-8") + (b"\n" + tail if tail else b"")
            changes[source] = replacement
            changes[sidecar] = (
                (json.dumps(delta, indent=4) + "\n").encode("utf-8") if delta else None
            )
    for path, content in changes.items():
        if content is not None:
            destination = stage / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
    return changes

"""Component-level field-default overrides adjacent to readable source."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .domain import Component


def defaults_path(source: Path) -> Path:
    return source.with_suffix(".fielddefaults.json")


def minimal_component_defaults(
    source: Path, overrides: dict[str, Any]
) -> dict[str, Any]:
    from . import native_styles

    parent = native_styles.parent_styles(source.parent)
    return native_styles.difference(parent, native_styles.resolve(parent, overrides))


def write_component_defaults(source: Path, overrides: dict[str, Any]) -> None:
    """Write only differences from the effective app; remove an empty file."""
    values = minimal_component_defaults(source, overrides)
    from .image_assets import stylesheet_assets

    values = stylesheet_assets(
        values, source.parent, exporting=True, owner=source.stem + "-style"
    )
    path = defaults_path(source)
    if values:
        path.write_text(
            json.dumps(values, indent=4) + "\n", encoding="utf-8", newline="\n"
        )
    else:
        path.unlink(missing_ok=True)


def encode_source_w4gl(component: Component) -> str:
    """The disk format puts field defaults in JSON, never in the TOML header."""
    from .parser import encode_w4gl

    props = {
        key: value for key, value in component.props.items() if key != "fielddefaults"
    }
    return encode_w4gl(replace(component, props=props))

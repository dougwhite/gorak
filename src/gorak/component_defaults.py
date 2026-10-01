"""Component-level field-default overrides adjacent to readable source."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from .domain import Component
from .errors import ProjectError
from .field_defaults import (
    diff_defaults,
    effective_defaults,
    is_field_style,
    merge_defaults,
    next_field_style_index,
    read_defaults,
)


def defaults_path(source: Path) -> Path:
    return source.with_suffix(".fielddefaults.json")


def read_component_defaults(source: Path, inline: Any) -> dict[str, Any]:
    """Read the new file or legacy TOML, refusing two competing definitions."""
    if not isinstance(inline, dict):
        raise ProjectError("Component field defaults must be an object")
    path = defaults_path(source)
    if not path.exists():
        return inline
    if inline:
        raise ProjectError(
            f"Field defaults exist in both TOML and {path.name}; keep one definition"
        )
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as ex:
        raise ProjectError(f"Cannot read component field defaults {path}: {ex}") from ex
    if not isinstance(values, dict):
        raise ProjectError(f"Component field defaults must be an object: {path}")
    return values


def minimal_component_defaults(
    source: Path, overrides: dict[str, Any]
) -> dict[str, Any]:
    repo = read_defaults(source.parent.parent / "field_defaults.json")
    app = read_defaults(source.parent / "field_defaults.json")
    if "structure" in repo or "structure" in app:
        from .palette import difference, merge

        parent = merge(repo, app)
        return difference(parent, merge(parent, overrides))
    parent = effective_defaults(repo, app, {})
    result = diff_defaults(parent, overrides)
    styles = overrides.get("field_styles")
    inherited = parent.get("field_styles")
    if (
        isinstance(styles, list)
        and isinstance(inherited, list)
        and all(is_field_style(style) for style in styles + inherited)
    ):
        # Diff the supplied override rows, not the whole effective palette.
        # A different row count must not copy inherited styles into the file.
        merged = deepcopy(inherited)
        cursor = 0
        rows = []
        for style in styles:
            index = next_field_style_index(merged, style, cursor)
            if index is None:
                rows.append(deepcopy(style))
                merged.append(deepcopy(style))
                cursor = len(merged)
            else:
                properties = diff_defaults(
                    merged[index]["properties"], style["properties"]
                )
                rows.append(
                    {
                        "type": style["type"],
                        "group": style["group"],
                        "properties": properties,
                    }
                )
                merged[index]["properties"] = merge_defaults(
                    merged[index]["properties"], style["properties"]
                )
                cursor = index + 1
        # Empty identity rows can be necessary to select a later duplicate
        # style. Remove one only when the resulting effective palette agrees.
        for index in reversed(range(len(rows))):
            if rows[index]["properties"]:
                continue
            candidate = rows[:index] + rows[index + 1 :]
            if (
                merge_defaults(parent, {"field_styles": candidate}).get("field_styles")
                == merged
            ):
                rows = candidate
        if rows:
            result["field_styles"] = rows
        else:
            result.pop("field_styles", None)
    if effective_defaults(parent, {}, result) != effective_defaults(
        parent, {}, overrides
    ):
        raise ProjectError(
            f"Cannot minimize field defaults without changing their meaning: {source}"
        )
    return result


def write_component_defaults(source: Path, overrides: dict[str, Any]) -> None:
    """Write only differences from the effective app; remove an empty file."""
    values = minimal_component_defaults(source, overrides)
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

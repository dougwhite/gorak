"""Persist OpenROAD export change metadata under the local cache."""

from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from .database import ComponentSyncMetadata
from .project import read_json, write_json

STATE_VERSION = 1
STATE_PATH = ".openroad/gorak-state.json"


def state_path(root: Path) -> Path:
    return root / STATE_PATH


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        return {"version": STATE_VERSION, "components": {}}

    state = read_json(path)
    state.setdefault("version", STATE_VERSION)
    state.setdefault("components", {})
    return state


def save_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, state)


def component_key(app: str, component: str) -> str:
    return f"{app}/{component}"


def component_entries(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = state.get("components", {})
    if not isinstance(entries, dict):
        return {}

    return cast(dict[str, dict[str, Any]], entries)


def update_component_entries(
    root: Path,
    metadata: list[ComponentSyncMetadata],
) -> None:
    state = load_state(root)
    entries = component_entries(state)
    for item in metadata:
        entries[component_key(item.application_name, item.component_name)] = asdict(item)
    state["components"] = entries
    save_state(root, state)


def component_changed(
    entry: dict[str, Any] | None,
    metadata: ComponentSyncMetadata,
) -> bool:
    if entry is None:
        return True

    return any(
        entry.get(key) != getattr(metadata, key)
        for key in [
            "version_entity_id",
            "alter_date",
            "alter_count",
        ]
    )

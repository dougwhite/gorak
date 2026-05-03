from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Application:
    """OpenROAD application metadata."""

    name: str
    start_component: str
    description: str


@dataclass(frozen=True)
class ComponentInfo:
    """OpenROAD component metadata."""

    application_name: str
    name: str
    type: str
    description: str


@dataclass
class Component:
    """OpenROAD source component metadata and script."""

    name: str
    type: str
    props: dict[str, Any]
    script: str | None = None

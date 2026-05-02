from dataclasses import dataclass


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

from dataclasses import dataclass


@dataclass(frozen=True)
class Application:
    """OpenROAD application metadata."""

    name: str
    start_component: str
    description: str

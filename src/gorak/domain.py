from dataclasses import dataclass, field
from typing import Any

IncludedApplication = str | dict[str, str]


@dataclass(frozen=True)
class Application:
    """OpenROAD application metadata."""

    name: str
    start_component: str
    description: str
    database_name: str = ""
    database_type: str = ""


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
    markup: str | None = None


@dataclass(frozen=True)
class ApplicationExport:
    """OpenROAD full application XML export."""

    application: Application
    components: list[Component]
    included_applications: list[IncludedApplication] = field(default_factory=list)

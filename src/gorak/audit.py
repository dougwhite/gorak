"""Report OpenROAD XML export nodes not currently represented by Gorak files."""

from pathlib import Path
from typing import Any

from lxml import etree

from .parser import NS, xml_root

REPRESENTED_APP_CHILDREN = {
    "database_type",
    "databasename",
    "included_apps",
    "proc_start",
    "procstart",
    "short_remark",
    "versshortremarks",
}
REPRESENTED_COMPONENT_CHILDREN = {
    "attributes",
    "fielddefaults",
    "methods",
    "script",
    "taggedvalues",
}
REPRESENTED_FRAME_CHILDREN = {
    "startmenu",
    "topform",
}
UNREPRESENTED_COMPONENT_CHILDREN = {
    "extension",
    "queries",
}


def audit_xml_file(path: str) -> dict[str, Any]:
    """Audit one OpenROAD XML export file by path."""

    return {"path": path, **audit_xml(etree.parse(path))}


def audit_project_xml(root: Path) -> list[dict[str, Any]]:
    """Audit every cached OpenROAD XML export under one Gorak project."""

    cache_root = root / ".openroad"
    if not cache_root.is_dir():
        return []

    return [
        audit_xml_file(str(path.relative_to(root)))
        for path in sorted(cache_root.rglob("*.xml"))
    ]


def filter_missing_only(report: dict[str, Any]) -> dict[str, Any] | None:
    """Keep only application/component entries with missing XML paths."""

    application = report.get("application")
    filtered_application = (
        application
        if isinstance(application, dict) and application.get("missing_paths")
        else None
    )
    filtered_components = [
        component
        for component in report.get("components", [])
        if isinstance(component, dict) and component.get("missing_paths")
    ]
    if filtered_application is None and not filtered_components:
        return None

    filtered = dict(report)
    filtered["application"] = filtered_application
    filtered["components"] = filtered_components
    return filtered


def filter_reports_missing_only(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter a project audit report list down to entries with missing paths."""

    return [
        filtered
        for report in reports
        if (filtered := filter_missing_only(report)) is not None
    ]


def audit_xml(tree: etree._ElementTree | etree._Element) -> dict[str, Any]:
    """Return unsupported XML paths in a simple JSON-compatible shape."""

    root = xml_root(tree)
    app_node = root.find("./APPLICATION")
    components = root.findall("./COMPONENT")

    return {
        "application": audit_application_node(app_node) if app_node is not None else None,
        "components": [audit_component_node(component) for component in components],
    }


def audit_application_node(node: etree._Element) -> dict[str, Any]:
    name = node.get("name", "")
    return {
        "name": name,
        "missing_paths": [
            f"APPLICATION[{name}]/{child.tag}"
            for child in node
            if child.tag not in REPRESENTED_APP_CHILDREN
        ],
    }


def audit_component_node(node: etree._Element) -> dict[str, Any]:
    name = node.get("name", "")
    component_type = node.get(f"{{{NS['xsi']}}}type", "")
    represented_children = set(REPRESENTED_COMPONENT_CHILDREN)
    if component_type == "framesource":
        represented_children.update(REPRESENTED_FRAME_CHILDREN)

    return {
        "name": name,
        "type": component_type,
        "missing_paths": [
            f"COMPONENT[{name}]/{child.tag}"
            for child in node
            if not is_represented_component_child(child, represented_children)
        ],
    }


def is_represented_component_child(
    child: etree._Element,
    represented_children: set[str],
) -> bool:
    if child.tag in UNREPRESENTED_COMPONENT_CHILDREN:
        return False
    if child.tag in represented_children:
        return True

    return len(child) == 0

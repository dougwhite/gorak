"""Partial export reporting and preservation of failed component baselines."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from lxml import etree

from .project import ProjectError, write_json


class ComponentProjectionError(ProjectError):
    """A native component cannot be represented in readable source."""


@dataclass(frozen=True)
class ExportFailure:
    application: str
    component: str
    reason: str

    @property
    def identity(self) -> str:
        return f"{self.application}!{self.component}"

    def message(self) -> str:
        return f"Unable to export component `{self.identity}`: {self.reason}"


def failure_summary(exported: int, failures: list[ExportFailure]) -> str:
    label = "failure" if len(failures) == 1 else "failures"
    component_label = "component" if exported == 1 else "components"
    lines = [f"{exported} {component_label} exported, {len(failures)} {label}"]
    lines.extend(f"- {failure.identity}: {failure.reason}" for failure in failures)
    return "\n".join(lines)


def cached_components(directory: Path) -> dict[str, etree._Element]:
    from .portable_source import read_document

    nodes: dict[str, etree._Element] = {}
    for path in sorted(directory.glob("*.xml"), key=lambda p: p.stat().st_mtime_ns):
        tree = read_document(path)
        if tree.find("APPLICATION") is not None:
            nodes.clear()
        for node in tree.findall("COMPONENT"):
            nodes[(node.get("name") or "").casefold()] = deepcopy(node)
    return nodes


def finalize_baseline(
    xml_path: Path,
    failures: list[ExportFailure],
    previous: dict[str, etree._Element],
) -> None:
    """Do not record a failed projection as a successfully exported baseline."""
    from .portable_source import read_document

    report = xml_path.parent / "export-failures.json"
    if not failures:
        report.unlink(missing_ok=True)
        return
    archive = xml_path.parent / "export-errors" / uuid4().hex
    archive.mkdir(parents=True)
    (archive / xml_path.name).write_bytes(xml_path.read_bytes())
    write_json(report, {"failures": [asdict(f) for f in failures]})
    tree = read_document(xml_path)
    failed = {f.component.casefold() for f in failures}
    for node in list(tree.findall("COMPONENT")):
        if (node.get("name") or "").casefold() in failed:
            tree.remove(node)
    for name in sorted(failed):
        if name in previous:
            tree.append(deepcopy(previous[name]))
    xml_path.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True))


def failed_source(path: Path, failures: list[ExportFailure]) -> bool:
    """Match component files without treating shared assets as component-owned."""
    for suffix in (
        ".w4gl",
        ".wml",
        ".fielddefaults.json",
        ".queries.json",
        ".icons.json",
        ".xml",
    ):
        if path.name.endswith(suffix):
            name = path.name.removesuffix(suffix).casefold()
            return any(name == f.component.casefold() for f in failures)
    return False

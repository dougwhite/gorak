"""Run applications and interpret the OpenROAD unit framework's XML reports."""

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .project import ProjectError, read_json


@dataclass(frozen=True)
class TestApplication:
    application: str
    component: str | None = None
    timeout_seconds: int = 120


@dataclass(frozen=True)
class TestSummary:
    tests: int
    failures: int
    errors: int
    skipped: int
    messages: list[str] = field(default_factory=list)


def test_applications(root: Path) -> list[TestApplication]:
    entries = read_json(root / "gorak.json").get("tests")
    if not isinstance(entries, list) or not entries:
        raise ProjectError(
            "Configure a nonempty tests array in gorak.json or pass --app"
        )
    result = []
    for entry in entries:
        if isinstance(entry, str):
            entry = {"application": entry}
        if not isinstance(entry, dict) or not isinstance(entry.get("application"), str):
            raise ProjectError("Each tests entry must name an application")
        if set(entry) - {
            "application",
            "component",
            "timeout_seconds",
        }:
            raise ProjectError("Unknown test application configuration field")
        timeout = entry.get("timeout_seconds", 120)
        if type(timeout) is not int or not 1 <= timeout <= 86400:
            raise ProjectError(
                "Test timeout_seconds must be an integer from 1 to 86400"
            )
        for key in ["component"]:
            if entry.get(key) is not None and not isinstance(entry[key], str):
                raise ProjectError(f"Test {key} must be a string")
        result.append(TestApplication(**entry))
    return result


def report_summary(text: str) -> TestSummary:
    """Validate complete leaf-suite counts before treating a report as a result."""
    try:
        root = etree.fromstring(
            text.encode("utf-8"),
            etree.XMLParser(resolve_entities=False, no_network=True),
        )
        if root.getroottree().docinfo.doctype or root.tag not in {
            "testsuites",
            "testsuite",
        }:
            raise ValueError("Unsupported test report")
        suites = [
            node for node in root.iter("testsuite") if not node.findall("testsuite")
        ]
        if not suites:
            raise ValueError("No test suites reported")
        totals = [0, 0, 0, 0]
        messages = []
        for suite in suites:
            cases = suite.findall("testcase")
            counts = [
                len(cases),
                sum(c.find("failure") is not None for c in cases),
                sum(c.find("error") is not None for c in cases),
                sum(c.find("skipped") is not None for c in cases),
            ]
            for i, key in enumerate(["tests", "failures", "errors", "skipped"]):
                if key in suite.attrib and int(suite.attrib[key]) != counts[i]:
                    raise ValueError(
                        f"Incomplete report: {key} count does not match test cases"
                    )
                totals[i] += counts[i]
            for case in cases:
                for problem in [*case.findall("failure"), *case.findall("error")]:
                    name = ".".join(
                        filter(None, [case.get("classname"), case.get("name")])
                    )
                    messages.append(
                        f"{name}: {problem.get('message') or problem.text or 'No diagnostic'}"
                    )
        if totals[0] == 0:
            raise ValueError("No tests executed")
        return TestSummary(totals[0], totals[1], totals[2], totals[3], messages)
    except (etree.XMLSyntaxError, ValueError) as ex:
        raise ProjectError(f"Invalid or missing test results: {ex}") from ex

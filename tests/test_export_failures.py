"""Broken catalog entries and projections must not hide successful exports."""

from pathlib import Path
from typing import Any

import pytest

from gorak import cli, export
from gorak.connection import OpenRoadConnection
from gorak.domain import Application, ComponentInfo
from gorak.export_failures import cached_components, finalize_baseline
from gorak.project import ProjectError

CONNECTION = OpenRoadConnection("local", "node", "source", None)


def component(name: str, kind: str = "proc4glsource") -> str:
    return f'<COMPONENT name="{name}" xsi:type="{kind}"><script>RETURN 1;</script><datatype>integer</datatype></COMPONENT>'


def document(app: str, *nodes: str) -> str:
    return (
        '<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        + f'<APPLICATION name="{app}"/>'
        + "".join(nodes)
        + "</OPENROAD>"
    )


def setup_export(monkeypatch: pytest.MonkeyPatch, xml: str, names: list[str]) -> None:
    monkeypatch.setattr(
        export, "backup_application_xml", lambda c, a, p: p.write_text(xml)
    )
    monkeypatch.setattr(
        export,
        "read_components",
        lambda c, a: [ComponentInfo(a, n, "framesource", "") for n in names],
    )


def test_omissions_and_unsupported_types_do_not_stop_later_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_export(
        monkeypatch,
        document(
            "example",
            component("first"),
            component("broken", "futuretype"),
            component("last"),
        ),
        ["first", "broken", "missing", "last"],
    )
    paths = export.application_export_paths(tmp_path, "example")
    messages: list[str] = []
    result = export.export_application_to_paths(
        CONNECTION, "example", paths, messages.append
    )
    assert [c.name for c in result.components] == ["first", "last"]
    assert [f.identity for f in result.failures] == [
        "example!missing",
        "example!broken",
    ]
    assert any("Unable to export component `example!missing`" in m for m in messages)
    assert (paths.source_dir / "last.w4gl").is_file()
    assert not (paths.source_dir / "broken.w4gl").exists()
    summary = cli.application_export_summary(tmp_path, result)
    assert "2 components exported, 2 failures" in summary
    assert "example!broken" in summary and "example!missing" in summary
    finalize_baseline(paths.xml_path, result.failures, {})
    assert set(cached_components(paths.xml_path.parent)) == {"first", "last"}
    assert not (paths.xml_path.parent / "export-failures.json").exists()
    assert len(list((paths.xml_path.parent / "export-errors").glob("*/*.xml"))) == 1


@pytest.mark.parametrize("error_type", [ProjectError, ValueError, TypeError, KeyError])
def test_late_conversion_failure_preserves_entire_existing_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    setup_export(
        monkeypatch,
        document("example", component("broken"), component("last")),
        ["broken", "last"],
    )
    folder = tmp_path / "example"
    folder.mkdir()
    for suffix in (".w4gl", ".wml", ".queries.json", ".fielddefaults.json"):
        (folder / f"broken{suffix}").write_text("original" + suffix)
    from gorak.component_defaults import write_projected_defaults

    original = write_projected_defaults

    def write_defaults(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.stem == "broken":
            raise error_type("Invalid native stylesheet")
        original(path, *args, **kwargs)

    monkeypatch.setattr(export, "write_projected_defaults", write_defaults)
    result = export.export_application_to_paths(
        CONNECTION,
        "example",
        export.application_export_paths(tmp_path, "example"),
        None,
    )
    assert [c.name for c in result.components] == ["last"]
    for suffix in (".w4gl", ".wml", ".queries.json", ".fielddefaults.json"):
        assert (folder / f"broken{suffix}").read_text() == "original" + suffix


def test_component_failure_restores_cached_xml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = export.component_export_paths(tmp_path, "example", "broken")
    paths.xml_path.parent.mkdir(parents=True)
    original = document("example", component("broken"))
    paths.xml_path.write_text(original)
    xml = (
        '<OPENROAD xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        + component("broken", "futuretype")
        + "</OPENROAD>"
    )
    monkeypatch.setattr(
        export, "backup_component_xml", lambda c, a, n, p: p.write_text(xml)
    )
    with pytest.raises(ProjectError, match="Unsupported component type"):
        export.export_component_to_paths(CONNECTION, "example", "broken", paths)
    assert paths.xml_path.read_text() == original
    assert not paths.w4gl_path.exists()


def test_failed_component_cannot_escape_source_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_export(
        monkeypatch, document("example", component("../escape"), component("last")), []
    )
    result = export.export_application_to_paths(
        CONNECTION,
        "example",
        export.application_export_paths(tmp_path, "example"),
        None,
    )
    assert len(result.failures) == 1
    assert [c.name for c in result.components] == ["last"]
    assert not (tmp_path / "escape.w4gl").exists()


def test_cli_reports_partial_export_only_after_successes_are_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "gorak.json").write_text('{"name":"example"}')
    (tmp_path / ".env").write_text(
        "GORAK_BACKEND=local\nGORAK_VNODE=node\nGORAK_DATABASE=source\n"
    )
    monkeypatch.chdir(tmp_path)
    setup_export(
        monkeypatch, document("example", component("last")), ["missing", "last"]
    )
    monkeypatch.setattr(export, "read_application", lambda c, a: Application(a, "", ""))
    with pytest.raises(SystemExit) as error:
        cli.main(["app", "export", "example"])
    assert error.value.code == 1
    assert (tmp_path / "example/last.w4gl").is_file()
    output = capsys.readouterr()
    assert "Unable to export component `example!missing`" in output.out
    assert "1 component exported, 1 failure" in output.err
    assert "example!missing" in output.err


def test_unexpected_procedure_stylesheet_still_fails_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = component("broken").replace("</COMPONENT>", "<fielddefaults/></COMPONENT>")
    setup_export(
        monkeypatch, document("example", broken, component("last")), ["broken", "last"]
    )
    result = export.export_application_to_paths(
        CONNECTION,
        "example",
        export.application_export_paths(tmp_path, "example"),
        None,
    )
    assert [c.name for c in result.components] == ["last"]
    assert [f.component for f in result.failures] == ["broken"]


def test_broken_parent_styles_do_not_stop_procedures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup_export(
        monkeypatch,
        document("example", component("broken", "framesource"), component("last")),
        ["broken", "last"],
    )
    (tmp_path / "field_defaults.json").write_text('{"standalone": false}')
    result = export.export_application_to_paths(
        CONNECTION,
        "example",
        export.application_export_paths(tmp_path, "example"),
        None,
    )
    assert [c.name for c in result.components] == ["last"]
    assert [f.component for f in result.failures] == ["broken"]


def test_previous_baseline_streams_only_failed_components(tmp_path: Path) -> None:
    from gorak.export_failures import cached_components

    p = tmp_path / "app.xml"
    p.write_text(
        '<OPENROAD><APPLICATION name="example"/><COMPONENT name="first"/><COMPONENT name="second"/></OPENROAD>'
    )
    nodes = cached_components(tmp_path, {"second"})
    assert set(nodes) == {"second"}
    assert nodes["second"].getparent() is None

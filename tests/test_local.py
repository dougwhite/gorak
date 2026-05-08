import subprocess
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from gorak.domain import Application, ComponentInfo
from gorak.local import (
    LocalCommandError,
    backup_application,
    backup_component,
    build_backup_application_command,
    build_backup_component_command,
    build_database_target,
    build_sql_command,
    component_list_query,
    get_app_list,
    get_component_list,
    get_include_list,
    include_list_query,
    run_subprocess,
)

APP_LIST_OUTPUT = """
+--------------------------------+--------------------------------+------------------------------------------------------------+
|application_name                |start_component                 |short_remark                                                |
+--------------------------------+--------------------------------+------------------------------------------------------------+
|sample_app                      |fm_start                        |Example application                                         |
+--------------------------------+--------------------------------+------------------------------------------------------------+
"""

COMPONENT_LIST_OUTPUT = """
+--------------------------------+--------------------------------+--------------------------------+------------------------------------------------------------+
|application_name                |component_name                  |entity_type                     |short_remark                                                |
+--------------------------------+--------------------------------+--------------------------------+------------------------------------------------------------+
|sample_app                      |p4_start                        |proc4glsource                   |Startup procedure                                           |
+--------------------------------+--------------------------------+--------------------------------+------------------------------------------------------------+
"""

INCLUDE_LIST_OUTPUT = """
+--------------------------------+--------------------------------+----------------------------------------------------------------+-------------+
|application_name                |incl_name                       |incl_filename                                                   |incl_sequence|
+--------------------------------+--------------------------------+----------------------------------------------------------------+-------------+
|sample_app                      |source_include                  |                                                                |            1|
|sample_app                      |image_include                   |image_include.pkg                                               |            2|
+--------------------------------+--------------------------------+----------------------------------------------------------------+-------------+
"""


def test_build_database_target_uses_vnode_when_present() -> None:
    assert build_database_target("myvnode", "exampledb") == "myvnode::exampledb"


def test_build_backup_component_command() -> None:
    command = build_backup_component_command(
        vnode="myvnode",
        database="exampledb",
        app="sample_app",
        component="p4_start",
        output_path=Path("sample_app/p4_start.xml"),
        log_path=Path("sample_app/p4_start.log"),
    )

    assert command == [
        "w4gldev",
        "backupapp",
        "out",
        "myvnode::exampledb",
        "sample_app",
        "sample_app/p4_start.xml",
        "-nowindows",
        "-cp4_start",
        "-xml",
        "-TALL,logonly",
        "-Lsample_app/p4_start.log",
    ]


def test_build_backup_application_command() -> None:
    command = build_backup_application_command(
        vnode="myvnode",
        database="exampledb",
        app="sample_app",
        output_path=Path("sample_app/sample_app.xml"),
        log_path=Path("sample_app/sample_app.log"),
    )

    assert command == [
        "w4gldev",
        "backupapp",
        "out",
        "myvnode::exampledb",
        "sample_app",
        "sample_app/sample_app.xml",
        "-nowindows",
        "-xml",
        "-TALL,logonly",
        "-Lsample_app/sample_app.log",
    ]


def test_build_sql_command() -> None:
    assert build_sql_command("myvnode", "exampledb") == ["sql", "myvnode::exampledb"]


def test_backup_component_writes_to_requested_xml_path(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    output_path = tmp_path / "sample_app" / "p4_start.xml"

    def fake_run(command: list[str], input_text: str | None = None) -> str:
        calls.append(command)
        output_path.write_text("<xml />")
        return ""

    result = backup_component(
        vnode="myvnode",
        database="exampledb",
        app="sample_app",
        component="p4_start",
        output_path=output_path,
        run_cmd=fake_run,
    )

    assert result == str(output_path)
    assert output_path.read_text() == "<xml />"
    assert calls[0][:6] == [
        "w4gldev",
        "backupapp",
        "out",
        "myvnode::exampledb",
        "sample_app",
        str(output_path),
    ]


def test_backup_component_errors_when_export_file_is_missing(tmp_path: Path) -> None:
    def fake_run(command: list[str], input_text: str | None = None) -> str:
        return ""

    with pytest.raises(LocalCommandError) as ex:
        backup_component(
            vnode="myvnode",
            database="exampledb",
            app="sample_app",
            component="p4_start",
            output_path=tmp_path / "sample_app" / "p4_start.xml",
            run_cmd=fake_run,
        )

    assert "Export did not create expected file" in str(ex.value)


def test_backup_application_writes_to_requested_xml_path(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    output_path = tmp_path / "sample_app" / "sample_app.xml"

    def fake_run(command: list[str], input_text: str | None = None) -> str:
        calls.append(command)
        output_path.write_text("<xml />")
        return ""

    result = backup_application(
        vnode="myvnode",
        database="exampledb",
        app="sample_app",
        output_path=output_path,
        run_cmd=fake_run,
    )

    assert result == str(output_path)
    assert output_path.read_text() == "<xml />"
    assert calls[0] == [
        "w4gldev",
        "backupapp",
        "out",
        "myvnode::exampledb",
        "sample_app",
        str(output_path),
        "-nowindows",
        "-xml",
        "-TALL,logonly",
        calls[0][-1],
    ]
    assert calls[0][-1].startswith("-L")
    assert "-cp4_start" not in calls[0]


def test_backup_application_errors_when_export_file_is_missing(
    tmp_path: Path,
) -> None:
    def fake_run(command: list[str], input_text: str | None = None) -> str:
        return ""

    with pytest.raises(LocalCommandError) as ex:
        backup_application(
            vnode="myvnode",
            database="exampledb",
            app="sample_app",
            output_path=tmp_path / "sample_app" / "sample_app.xml",
            run_cmd=fake_run,
        )

    assert "Export did not create expected file" in str(ex.value)


def test_get_app_list_runs_sql_with_packaged_query() -> None:
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], input_text: str | None = None) -> str:
        calls.append((command, input_text))
        return APP_LIST_OUTPUT

    result = get_app_list("myvnode", "exampledb", run_cmd=fake_run)

    assert result == [
        Application(
            name="sample_app",
            start_component="fm_start",
            description="Example application",
        )
    ]
    command, input_text = calls[0]
    assert command == ["sql", "myvnode::exampledb"]
    assert input_text is not None
    assert "select e.entity_name as application_name" in input_text


def test_get_component_list_runs_sql_for_application() -> None:
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], input_text: str | None = None) -> str:
        calls.append((command, input_text))
        return COMPONENT_LIST_OUTPUT

    result = get_component_list(
        vnode="myvnode",
        database="exampledb",
        app="sample_app",
        run_cmd=fake_run,
    )

    assert result == [
        ComponentInfo(
            application_name="sample_app",
            name="p4_start",
            type="proc4glsource",
            description="Startup procedure",
        )
    ]
    command, input_text = calls[0]
    assert command == ["sql", "myvnode::exampledb"]
    assert input_text is not None
    assert "and lower(ea.entity_name) = lower('sample_app')" in input_text


def test_component_list_query_escapes_application_name() -> None:
    assert "and lower(ea.entity_name) = lower('owner''s_app')" in component_list_query(
        "owner's_app"
    )


def test_get_include_list_runs_sql_for_application() -> None:
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(command: list[str], input_text: str | None = None) -> str:
        calls.append((command, input_text))
        return INCLUDE_LIST_OUTPUT

    result = get_include_list(
        vnode="myvnode",
        database="exampledb",
        app="sample_app",
        run_cmd=fake_run,
    )

    assert result == [
        "source_include",
        {"name": "image_include", "image": "image_include.pkg"},
    ]
    command, input_text = calls[0]
    assert command == ["sql", "myvnode::exampledb"]
    assert input_text is not None
    assert "from ii_incl_apps i" in input_text
    assert "and lower(e.entity_name) = lower('sample_app')" in input_text


def test_include_list_query_escapes_application_name() -> None:
    assert "and lower(e.entity_name) = lower('owner''s_app')" in include_list_query(
        "owner's_app"
    )


def test_run_subprocess_passes_stdin_to_process(monkeypatch: MonkeyPatch) -> None:
    calls: list[object] = []

    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
        input: str | None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(
            {
                "command": command,
                "check": check,
                "capture_output": capture_output,
                "text": text,
                "input": input,
            }
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="sql output",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_subprocess(["sql", "myvnode::exampledb"], "select 1")

    assert result == "sql output"
    assert calls == [
        {
            "command": ["sql", "myvnode::exampledb"],
            "check": True,
            "capture_output": True,
            "text": True,
            "input": "select 1",
        }
    ]


def test_run_subprocess_raises_on_failure(monkeypatch: MonkeyPatch) -> None:
    def fake_run(
        command: list[str],
        check: bool,
        capture_output: bool,
        text: bool,
        input: str | None,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            output="bad stdout",
            stderr="bad stderr",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(LocalCommandError) as ex:
        run_subprocess(["sql", "myvnode::exampledb"], "select 1")

    assert "Local command failed with exit code 1" in str(ex.value)
    assert "bad stdout" in str(ex.value)
    assert "bad stderr" in str(ex.value)

from collections.abc import Iterator
from typing import Any, cast

from gorak.database import (
    OdbcSettings,
    build_odbc_connection_string,
    get_app_list,
    get_component_list,
    get_include_list,
)
from gorak.domain import Application, ComponentInfo


class FakeConnection:
    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        statement: object,
        parameters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append((str(statement), parameters))
        if parameters is None:
            return [
                {
                    "application_name": "sample_app   ",
                    "start_component": "fm_start   ",
                    "short_remark": "Example application   ",
                }
            ]
        if "ii_incl_apps" in str(statement):
            return [
                {
                    "application_name": "sample_app",
                    "incl_name": "source_include",
                    "incl_filename": "",
                    "incl_sequence": 1,
                },
                {
                    "application_name": "sample_app",
                    "incl_name": "image_include",
                    "incl_filename": "image_include.pkg",
                    "incl_sequence": 2,
                },
            ]
        return [
            {
                "application_name": "sample_app",
                "component_name": "fm_start",
                "entity_type": "framesource",
                "short_remark": "Start frame",
            }
        ]


class FakeEngine:
    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    def connect(self) -> FakeConnection:
        return FakeConnection(self.calls)


def settings() -> OdbcSettings:
    return OdbcSettings(
        driver="Ingres AC",
        host="db-host.example",
        listen_address="II7",
        database="source_db",
        user="ingres",
        password="secret",
    )


def fake_engine_factory(calls: list[object]) -> Iterator[Any]:
    def factory(odbc_settings: OdbcSettings) -> FakeEngine:
        calls.append(odbc_settings)
        return FakeEngine(calls)

    yield factory


def test_build_odbc_connection_string_uses_actian_fields() -> None:
    assert build_odbc_connection_string(settings()) == (
        "Driver={Ingres AC};"
        "HostName=db-host.example;"
        "ListenAddress=II7;"
        "Database=source_db;"
        "UID=ingres;"
        "PWD=secret"
    )


def test_get_app_list_queries_openroad_application_metadata() -> None:
    calls: list[object] = []
    factory = next(fake_engine_factory(calls))

    assert get_app_list(settings(), engine_factory=factory) == [
        Application("sample_app", "fm_start", "Example application")
    ]
    assert calls[0] == settings()
    statement, parameters = cast(tuple[object, dict[str, object] | None], calls[1])
    assert "from ii_applications a" in str(statement)
    assert parameters is None


def test_get_component_list_queries_one_application() -> None:
    calls: list[object] = []
    factory = next(fake_engine_factory(calls))

    assert get_component_list(settings(), "sample_app", engine_factory=factory) == [
        ComponentInfo("sample_app", "fm_start", "framesource", "Start frame")
    ]
    assert calls[0] == settings()
    statement, parameters = cast(tuple[object, dict[str, object] | None], calls[1])
    assert "from ii_entities e" in str(statement)
    assert parameters == {"app_name": "sample_app"}


def test_get_include_list_queries_one_application() -> None:
    calls: list[object] = []
    factory = next(fake_engine_factory(calls))

    assert get_include_list(settings(), "sample_app", engine_factory=factory) == [
        "source_include",
        {"name": "image_include", "image": "image_include.pkg"},
    ]
    assert calls[0] == settings()
    statement, parameters = cast(tuple[object, dict[str, object] | None], calls[1])
    assert "from ii_incl_apps i" in str(statement)
    assert parameters == {"app_name": "sample_app"}

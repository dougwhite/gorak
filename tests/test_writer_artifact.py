import os
from pathlib import Path

import pytest

from gorak.project import ProjectError
from gorak.writer_artifact import (
    MAX_STARTUP_BYTES,
    startup_variable,
    writer_environment,
)


def test_preserves_environment_and_removes_artifact_after_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "original.sql"
    source.write_bytes(
        "set date_format 'multinational'; -- café\nset lockmode session where readlock=nolock".encode(
            "cp1252"
        )
    )
    original = {
        "ING_SET_SOURCE": f"include {source}",
        "ING_SET": "set lockmode session where timeout=30",
        "OTHER": "preserve",
    }
    seen: list[str] = []

    def unexpected_fallback(name: str) -> str:
        seen.append(name)
        return ""

    with pytest.raises(RuntimeError):
        with writer_environment(
            original,
            "source",
            installation_value=unexpected_fallback,
            encoding="cp1252",
            temporary_root=tmp_path,
        ) as child:
            artifact = Path(child["ING_SET_SOURCE"].removeprefix("include "))
            assert artifact.is_file()
            content = artifact.read_text(encoding="cp1252")
            assert "set date_format 'multinational'" in content
            assert "readlock=nolock" in content
            assert content.endswith(
                'set lockmode on "$ingres".gorak_revision_lanes where level=mvcc, readlock=shared\n'
            )
            assert child["ING_SET"] == original["ING_SET"]
            assert child["OTHER"] == "preserve"
            if os.name != "nt":
                assert artifact.stat().st_mode & 0o777 == 0o600
                assert artifact.parent.stat().st_mode & 0o777 == 0o700
            raise RuntimeError("child failed")
    assert not artifact.exists() and not artifact.parent.exists()
    assert original["ING_SET_SOURCE"] == f"include {source}"
    assert b"caf\xe9" in source.read_bytes()
    assert not seen


def test_symbol_table_fallback_and_overlapping_operations(tmp_path: Path) -> None:
    queried: list[str] = []

    def fallback(name: str) -> str:
        queried.append(name)
        return "set lockmode session where timeout=17"

    with writer_environment(
        {},
        "source",
        installation_value=fallback,
        encoding="ascii",
        temporary_root=tmp_path,
    ) as first:
        a = Path(first["ING_SET_SOURCE"][8:])
        with writer_environment(
            {},
            "source",
            installation_value=fallback,
            encoding="ascii",
            temporary_root=tmp_path,
        ) as second:
            b = Path(second["ING_SET_SOURCE"][8:])
            assert a != b and a.exists() and b.exists()
            assert "timeout=17" in b.read_text()
        assert a.exists() and not b.exists()
    assert not a.exists()
    assert queried == ["ING_SET_SOURCE", "ING_SET_SOURCE"]


@pytest.mark.parametrize(
    "name", ["node::source", "source/name", "bad-name", "x" * 33, ""]
)
def test_invalid_database(name: str) -> None:
    with pytest.raises(ProjectError):
        startup_variable(name)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-8-sig", "unknown"])
def test_invalid_encoding_leaves_no_artifacts(tmp_path: Path, encoding: str) -> None:
    with pytest.raises(ProjectError):
        with writer_environment(
            {},
            "source",
            installation_value=lambda _: "",
            encoding=encoding,
            temporary_root=tmp_path,
        ):
            pytest.fail("launched")
    assert not list(tmp_path.iterdir())


def test_missing_include_and_invalid_encoding_fail_before_launch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing.sql"
    for data in [None, b"\xff", b"x" * (MAX_STARTUP_BYTES + 1)]:
        if data is not None:
            path.write_bytes(data)
        with pytest.raises(ProjectError):
            with writer_environment(
                {"ING_SET_SOURCE": f"include {path}"},
                "source",
                installation_value=lambda _: "",
                encoding="utf-8",
                temporary_root=tmp_path,
            ):
                pytest.fail("launched")
        assert not list(tmp_path.glob("gorak-init-*"))


def test_ambiguous_case_and_empty_override(tmp_path: Path) -> None:
    with pytest.raises(ProjectError, match="Ambiguous"):
        with writer_environment(
            {"ING_SET_SOURCE": "", "ing_set_source": ""},
            "source",
            installation_value=lambda _: "",
            encoding="ascii",
        ):
            pytest.fail("launched")

    def unused(name: str) -> str:
        pytest.fail("explicit empty override must not read installation value")

    with writer_environment(
        {"ing_set_source": ""},
        "source",
        installation_value=unused,
        encoding="ascii",
        temporary_root=tmp_path,
    ) as child:
        assert "ing_set_source" not in child
        assert (
            Path(child["ING_SET_SOURCE"][8:]).read_text().startswith("set lockmode on")
        )

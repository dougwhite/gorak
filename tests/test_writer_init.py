import pytest

from gorak.project import ProjectError
from gorak.writer_init import compose_writer_init


def test_preserves_startup_and_ends_trailing_comment_before_override() -> None:
    existing = "set lockmode session where readlock=nolock, timeout=30 -- keep this"
    result = compose_writer_init(existing, "gorak_revision_lanes")
    assert result.startswith(
        "set lockmode session where readlock=nolock, timeout=30;\n"
    )
    assert "keep this" not in result
    assert result.endswith(
        'set lockmode on "$ingres".gorak_revision_lanes where level=mvcc, readlock=shared\n'
    )


def test_include_resolution_preserves_file_content_and_does_not_mutate_it() -> None:
    content = "/* site config */\nset date_format 'MULTINATIONAL4';\nset lockmode session where timeout=30;\n"
    seen = []

    def resolve(path: str) -> str:
        seen.append(path)
        return content

    result = compose_writer_init(
        'include "C:\\Site Config\\startup.sql"', "counter", read_include=resolve
    )
    assert seen == [r"C:\Site Config\startup.sql"]
    assert "set date_format 'MULTINATIONAL4';\n" in result
    assert "set lockmode session where timeout=30;\n" in result


@pytest.mark.parametrize(
    "sql",
    ["set x='a;b';", "set x='it''s'; -- tail", 'set x="a;b";', "", "-- comment only"],
)
def test_quoted_boundaries_and_empty_startup(sql: str) -> None:
    assert compose_writer_init(sql, "counter").endswith("readlock=shared\n")


@pytest.mark.parametrize(
    "sql",
    [
        "set x='unterminated",
        "set x=1; drop table t",
        "include relative.sql",
        "include /host/file.sql",
        "set x=1; /* open",
        "set x=1\0",
        "/* nested /* comment */ set x=1",
    ],
)
def test_unsafe_or_unresolved_startup_rejected(sql: str) -> None:
    with pytest.raises(ProjectError):
        compose_writer_init(sql, "counter")


def test_nested_include_is_not_silently_discarded() -> None:
    with pytest.raises(ProjectError, match="only SET"):
        compose_writer_init(
            "include /host/first.sql",
            "counter",
            read_include=lambda _: "include /host/second.sql",
        )


@pytest.mark.parametrize("table", ["x;drop table y", "other.counter", "A", "x" * 33])
def test_identifiers_rejected(table: str) -> None:
    with pytest.raises(ProjectError, match="identifier"):
        compose_writer_init("", table)


def test_comment_normalization_preserves_literal_text_and_statement_order() -> None:
    existing = "set example='-- keep; /*literal*/'; -- drop comment\nset other=1 /* explanation */;"
    result = compose_writer_init(existing, "counter")
    assert result.startswith("set example='-- keep; /*literal*/';\nset other=1;\n")
    assert "drop comment" not in result and "explanation" not in result


def test_multiline_literal_rejected_instead_of_rewriting_its_value() -> None:
    with pytest.raises(ProjectError, match="Multiline"):
        compose_writer_init("set example='first\nsecond'", "counter")

"""Full migration must preserve source independently of its staged encoding."""

from pathlib import Path

import pytest

from gorak import source_migration
from gorak.component_defaults import encode_source_w4gl
from gorak.contract_source import decode_component
from gorak.domain import Component
from gorak.errors import ProjectError
from gorak.parser import parse_w4gl
from gorak.xml_text import text_value


def script_project(root: Path, script: str) -> Path:
    folder = root / "example"
    folder.mkdir()
    (folder / "app.json").write_text("{}", encoding="utf-8")
    source = folder / "sample.w4gl"
    source.write_text(
        "[proc4glsource]\n\n===\n" + script, encoding="utf-8", newline="\n"
    )
    return source


@pytest.mark.parametrize("code", [11, 12, 28, 29, 30, 31])
@pytest.mark.parametrize("trailing_whitespace", ["", " \t\r\n"])
def test_full_migration_preserves_trailing_control_characters(
    tmp_path: Path, code: int, trailing_whitespace: str
) -> None:
    expected = "// keep this character: " + chr(code)
    source = script_project(tmp_path, expected + trailing_whitespace)
    before = source.read_bytes()

    operation = source_migration.migrate_source(tmp_path)

    assert operation is not None
    assert source.read_bytes().endswith(expected.encode("utf-8") + b"\n")
    assert parse_w4gl(source.read_text(), source.stem).script == expected
    assert text_value(decode_component(source).find("script")) == expected
    assert (operation / "before/example/sample.w4gl").read_bytes() == before
    installed = source.read_bytes()
    assert source_migration.migrate_source(tmp_path) is None
    assert source.read_bytes() == installed


def test_full_migration_rejects_encoder_loss_before_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = script_project(tmp_path, "// keep this character: \x0c")
    before = {p: p.read_bytes() for p in source.parent.iterdir()}

    def lossy_encoder(component: Component) -> str:
        # Both the staged text and its re-encoding lose the same character.
        return encode_source_w4gl(component).rstrip()

    monkeypatch.setattr(source_migration, "encode_source_w4gl", lossy_encoder)
    with pytest.raises(ProjectError, match="migration verification failed"):
        source_migration.migrate_source(tmp_path)
    assert {p: p.read_bytes() for p in source.parent.iterdir()} == before
    assert not (tmp_path / ".openroad/pull-pending.json").exists()
    assert not list((tmp_path / ".openroad/migrations").glob("*/verified"))

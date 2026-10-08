"""Verified modal promotion across app and project inheritance boundaries."""

import json
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from gorak import native_styles as styles
from gorak import style_commands
from gorak.errors import ProjectError
from gorak.style_compaction import ordered_key


def native(first: str, second: str) -> dict[str, Any]:
    return {
        "properties": {},
        "group_order": ["entryfield"],
        "groups": {
            "entryfield": {
                "properties": {
                    "_type": "matrixfield",
                    "clienttext": "entryfield",
                    "childfields": "",
                },
                "styles": {
                    "style1": {"_type": "entryfield", "width": first},
                    "style2": {"_type": "entryfield", "width": second},
                },
            }
        },
    }


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def project(root: Path) -> list[Path]:
    write(root / "gorak.json", {"name": "synthetic"})
    write(root / "field_defaults.json", styles.complete(native("0", "0")))
    sources = []
    variants = {
        "alpha": [("10", "20"), ("10", "30"), ("40", "30")],
        "beta": [("10", "20"), ("10", "50"), ("60", "50")],
        "gamma": [("70", "50"), ("10", "50"), ("10", "90")],
    }
    for app, rows in variants.items():
        folder = root / app
        write(folder / "app.json", {})
        write(folder / "field_defaults.json", {})
        for index, values in enumerate(rows):
            source = folder / f"panel_{index}.w4gl"
            source.write_text(
                "[framesource]\n\n===\n// retained source\n", encoding="utf-8"
            )
            write(
                source.with_suffix(".fielddefaults.json"),
                styles.complete(native(*values)),
            )
            sources.append(source)
    absent = root / "alpha" / "absent.w4gl"
    absent.write_text("[framesource]\n\n===\n", encoding="utf-8")
    write(absent.with_suffix(".fielddefaults.json"), {"absent": True})
    return [*sources, absent]


def test_mixed_app_promotion_preserves_frames_and_is_readonly_in_dryrun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = project(tmp_path)
    before = {source: ordered_key(styles.frame_styles(source)) for source in sources}
    files = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert "Write" in style_commands.maintain(tmp_path, "compact", dry_run=True)
    assert all(path.read_bytes() == data for path, data in files.items())
    ticks = count()
    monkeypatch.setattr(style_commands, "monotonic", lambda: next(ticks))
    messages: list[str] = []
    style_commands.maintain(tmp_path, "compact", progress=messages.append)
    assert ordered_key(styles.project_styles(tmp_path)) == ordered_key(
        native("10", "50")
    )
    assert ordered_key(styles.parent_styles(tmp_path / "alpha")) == ordered_key(
        native("10", "30")
    )
    assert {
        source: ordered_key(styles.frame_styles(source)) for source in sources
    } == before
    assert all(source.read_bytes() == files[source] for source in sources)
    assert not (tmp_path / "beta" / "field_defaults.json").exists()
    assert not (tmp_path / "gamma" / "field_defaults.json").exists()
    assert style_commands.maintain(tmp_path, "compact") == "Stylesheets unchanged"
    assert any(
        "Reading and promoting" in message and "/" in message for message in messages
    )
    assert any("elapsed" in message and "ETA" in message for message in messages)
    assert "complete" in messages[-1]
    assert not (tmp_path / ".openroad" / "pull-pending.json").exists()
    assert not list((tmp_path / ".openroad" / "styles").iterdir())


def test_existing_empty_layers_are_trimmed_without_changing_inheritance(
    tmp_path: Path,
) -> None:
    write(tmp_path / "field_defaults.json", styles.complete(native("10", "20")))
    write(tmp_path / "alpha" / "app.json", {})
    write(tmp_path / "alpha" / "field_defaults.json", {})
    source = tmp_path / "alpha" / "panel.w4gl"
    source.write_text("[framesource]\n\n===\n", encoding="utf-8")
    sidecar = source.with_suffix(".fielddefaults.json")
    write(sidecar, {})
    before = ordered_key(styles.frame_styles(source))
    style_commands.maintain(tmp_path, "compact")
    assert not sidecar.exists()
    assert not (source.parent / "field_defaults.json").exists()
    assert ordered_key(styles.frame_styles(source)) == before


def test_failed_compaction_keeps_pending_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project(tmp_path)
    before = (tmp_path / "field_defaults.json").read_bytes()

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("synthetic installation failure")

    monkeypatch.setattr(style_commands, "apply_files", fail)
    with pytest.raises(OSError, match="synthetic installation failure"):
        style_commands.maintain(tmp_path, "compact")
    assert (tmp_path / ".openroad" / "pull-pending.json").exists()
    assert list((tmp_path / ".openroad" / "styles").iterdir())
    assert (tmp_path / "field_defaults.json").read_bytes() == before


@pytest.mark.parametrize(
    "valid, invalid",
    [
        (
            {"properties": {"true": "x"}, "group_order": [], "groups": {}},
            {"properties": {True: "x"}, "group_order": [], "groups": {}},
        ),
        (
            {"properties": {}, "group_order": [], "groups": {}},
            {"properties": {}, "group_order": (), "groups": {}},
        ),
    ],
)
def test_validation_cache_does_not_hide_invalid_native_types(
    valid: dict[str, Any], invalid: dict[str, Any]
) -> None:
    with pytest.raises(ProjectError):
        styles.decode(invalid)
    with styles.validation_scope():
        styles.validate(valid)
        with pytest.raises(ProjectError):
            styles.validate(invalid)

"""Fresh exports establish provenance without trusting pre-existing caches."""

from pathlib import Path

import pytest

from gorak import export, sync_guard
from gorak.connection import OpenRoadConnection
from gorak.domain import Application
from gorak.local import LocalCommandError
from gorak.project import GorakContext, GorakProject, ProjectError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("component", [False, True])
@pytest.mark.parametrize(
    "state",
    ["fresh", "legacy", "malformed", "tracked", "bound", "wrong_target", "failed"],
)
def test_export_binding_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, component: bool, state: str
) -> None:
    connection = OpenRoadConnection("local", "node", "source", None)
    context = GorakContext(GorakProject(tmp_path, "example"), {})
    target_path = tmp_path / ".openroad/sync-target.json"
    if state in {"legacy", "malformed"}:
        cache = tmp_path / ".openroad/older"
        cache.mkdir(parents=True)
        (cache / "older.xml").write_bytes(
            b"invalid old XML"
            if state == "malformed"
            else (FIXTURES / "fm_example_frame.xml").read_bytes()
        )
    elif state == "tracked":
        target_path.parent.mkdir()
        (target_path.parent / "tracked-applications.json").write_text('["older"]')
    elif state in {"bound", "wrong_target"}:
        sync_guard.save_binding(
            OpenRoadConnection(
                "local", "node", "other" if state == "wrong_target" else "source", None
            ),
            tmp_path,
        )
    original_target = target_path.read_bytes() if target_path.exists() else None
    calls = []

    def backup(vnode: str, database: str, app: str, **kwargs: object) -> str:
        calls.append(app)
        if state == "failed":
            raise LocalCommandError("Export failed")
        path = Path(str(kwargs["output_path"]))
        fixture = "fm_example_frame.xml" if component else "gorak_examples.xml"
        path.write_bytes((FIXTURES / fixture).read_bytes())
        return str(path)

    def metadata_failure(*args: object) -> None:
        raise LocalCommandError("Metadata unavailable")

    monkeypatch.setattr(
        export, "read_application", lambda *args: Application("sample_app", "", "")
    )
    monkeypatch.setattr(export, "local_backup_application", backup)
    monkeypatch.setattr(export, "local_backup_component", backup)
    monkeypatch.setattr(export, "record_component_sync_metadata", metadata_failure)
    messages: list[str] = []

    def run_export() -> None:
        if component:
            export.export_component(
                connection,
                context,
                "sample_app",
                "fm_example_frame",
                None,
                messages.append,
            )
        else:
            export.export_application(
                connection, context, "sample_app", None, messages.append
            )

    if state == "wrong_target":
        with pytest.raises(ProjectError, match="different configured target"):
            run_export()
        assert not calls
        assert target_path.read_bytes() == original_target
    elif state == "failed":
        with pytest.raises(LocalCommandError, match="Export failed"):
            run_export()
        assert not target_path.exists()
    else:
        run_export()
        assert any(
            "sync metadata could not be recorded" in message for message in messages
        )
        if state in {"legacy", "malformed", "tracked"}:
            assert not target_path.exists()
        else:
            assert sync_guard.binding_status(connection, tmp_path) == "verified"
            if original_target is not None:
                assert target_path.read_bytes() == original_target
            # Ordinary sync must accept this baseline without an explicit bind.
            # Database comparison is isolated from external OpenROAD services.
            monkeypatch.setattr(sync_guard, "plan_project", lambda *args: [])
            assert sync_guard.guard_sync(connection, tmp_path, push=False) == []

"""Synchronize local source files from changed OpenROAD database components."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .connection import OpenRoadConnection
from .database import ComponentSyncMetadata
from .export import (
    application_export_paths,
    component_export_paths,
    export_application_to_paths,
    export_component_to_paths,
    read_all_component_sync_metadata,
)
from .project import GorakContext, ProjectError
from .sync_state import (
    component_changed,
    component_entries,
    component_key,
    load_state,
    save_state,
)


@dataclass(frozen=True)
class SyncResult:
    checked: int
    changed: int
    exported: int


def sync_project(
    connection: OpenRoadConnection,
    context: GorakContext,
    progress: Callable[[str], None] | None = None,
) -> SyncResult:
    """Re-export database components whose OpenROAD change metadata changed."""

    if context.project is None:
        raise ProjectError("Sync requires a gorak project")

    root = context.project.root
    state = load_state(root)
    entries = component_entries(state)
    apps = tracked_applications(root, entries)
    if not apps:
        raise ProjectError("No exported applications found to sync")

    metadata = tracked_metadata(read_all_component_sync_metadata(connection), apps)
    changed = [
        item
        for item in metadata
        if component_changed(
            entries.get(component_key(item.application_name, item.component_name)),
            item,
        )
    ]
    if not changed:
        progress_message(progress, "No database changes found")

    exported = export_changed_components(connection, root, changed, metadata, progress)
    for item in metadata:
        entries[component_key(item.application_name, item.component_name)] = (
            component_state(item)
        )

    state["components"] = entries
    save_state(root, state)
    return SyncResult(checked=len(metadata), changed=len(changed), exported=exported)


def tracked_metadata(
    metadata: list[ComponentSyncMetadata],
    apps: list[str],
) -> list[ComponentSyncMetadata]:
    tracked = {app.lower() for app in apps}
    return [item for item in metadata if item.application_name.lower() in tracked]


def export_changed_components(
    connection: OpenRoadConnection,
    root: Path,
    changed: list[ComponentSyncMetadata],
    metadata: list[ComponentSyncMetadata],
    progress: Callable[[str], None] | None,
) -> int:
    exported = 0
    metadata_by_app = changes_by_app(metadata)
    for app, app_changes in changes_by_app(changed).items():
        if len(app_changes) > 1:
            progress_message(progress, f"Exporting changed application {app}")
            export_application_to_paths(
                connection=connection,
                app=app,
                paths=application_export_paths(root, app),
                progress=progress,
            )
            exported += len(metadata_by_app[app])
            continue

        item = app_changes[0]
        key = component_key(item.application_name, item.component_name)
        progress_message(progress, f"Exporting changed component {key}")
        export_component_to_paths(
            connection=connection,
            app=item.application_name,
            component=item.component_name,
            paths=component_export_paths(
                root,
                item.application_name,
                item.component_name,
            ),
        )
        exported += 1

    return exported


def changes_by_app(
    changed: list[ComponentSyncMetadata],
) -> dict[str, list[ComponentSyncMetadata]]:
    grouped: dict[str, list[ComponentSyncMetadata]] = {}
    for item in changed:
        grouped.setdefault(item.application_name, []).append(item)

    return grouped


def tracked_applications(root: Path, entries: dict[str, dict[str, object]]) -> list[str]:
    """Return apps known from state, falling back to project app folders."""

    apps = {
        key.split("/", 1)[0]
        for key in entries
        if "/" in key and key.split("/", 1)[0]
    }
    if apps:
        return sorted(apps)

    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir()
        and not path.name.startswith(".")
        and (path / "app.json").is_file()
    )


def component_state(metadata: ComponentSyncMetadata) -> dict[str, object]:
    return asdict(metadata)


def progress_message(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)

"""Target binding and conservative CLI gates while sync execution is migrated."""

import json
import socket
from pathlib import Path
from uuid import uuid4

from .connection import OpenRoadConnection
from .project import ProjectError
from .sync_plan import Change, baseline_inventory, plan_project


def target(connection: OpenRoadConnection) -> dict[str, str]:
    return {
        "backend": connection.backend,
        "host": connection.remote_host.ssh_target
        if connection.remote_host
        else socket.gethostname(),
        "vnode": connection.vnode,
        "database": connection.database,
    }


def binding_status(
    connection: OpenRoadConnection, root: Path, *, recover_push: bool = False
) -> str:
    if (root / ".openroad/pull-pending.json").exists():
        raise ProjectError(
            "An interrupted pull requires recovery; inspect .openroad/pull-pending.json and its before-images before continuing"
        )
    if not recover_push and (root / ".openroad/push-pending.json").exists():
        raise ProjectError(
            "An interrupted push requires recovery; inspect .openroad/push-pending.json"
        )
    path = root / ".openroad/sync-target.json"
    if not path.exists():
        return "unbound"
    try:
        saved = json.loads(path.read_text())
        if saved.get("version") != 1 or saved.get("target") != target(connection):
            raise ProjectError(
                "Sync baseline belongs to a different configured target; use a fresh checkout/cache for the new target"
            )
    except (ValueError, AttributeError) as ex:
        raise ProjectError("Invalid sync target record") from ex
    return "verified"


def save_binding(connection: OpenRoadConnection, root: Path) -> None:
    path = root / ".openroad/sync-target.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".sync-target-{uuid4().hex}.json")
    try:
        staged.write_text(
            json.dumps({"version": 1, "target": target(connection)}, indent=2) + "\n"
        )
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def can_bind_fresh_export(connection: OpenRoadConnection, root: Path) -> bool:
    """Only attribute a new export when no older baseline needs verification."""

    if binding_status(connection, root) != "unbound":
        return False
    cache = root / ".openroad"
    # Presence is sufficient: even unreadable/empty older XML has unknown origin.
    # Do not parse it merely to decide whether this is a first export.
    return not (cache / "tracked-applications.json").exists() and not any(
        cache.glob("*/*.xml")
    )


def guard_sync(
    connection: OpenRoadConnection,
    root: Path,
    *,
    push: bool,
    bind: bool = False,
    dry_run: bool = False,
    lock_held: bool = False,
) -> list[Change]:
    status = binding_status(connection, root)
    baseline, _ = baseline_inventory(root)
    has_sources = any(root.glob("*/app.json"))
    if connection.revision_generation and not bind and (has_sources or baseline):
        from .revision_checkpoint import revision_plan

        changes, _ = revision_plan(connection, root, lock_held=lock_held)
    else:
        changes = plan_project(connection, root) if has_sources or baseline else []
    if bind:
        changed = [c.key for c in changes if c.database != "unchanged"]
        if changed:
            raise ProjectError(
                "Cannot bind: database differs from cached baseline: "
                + ", ".join(changed)
            )
        save_binding(connection, root)
        return changes
    if status == "unbound" and baseline:
        raise ProjectError(
            "Existing cache has no verified target binding. Run gorak sync --bind to compare it with the database first"
        )
    blocked = []
    for change in changes:
        if change.action == "conflict":
            blocked.append(change)
        elif push and change.action == "pull":
            blocked.append(change)
        elif not push and change.action == "push":
            blocked.append(change)
        elif (
            push
            and change.action not in {"unchanged", "converged"}
            and "deleted"
            in {
                change.disk,
                change.database,
            }
        ):
            blocked.append(change)
    if blocked:
        details = "; ".join(
            f"{c.key}: disk {c.disk}, database {c.database}"
            + (f" ({c.reason})" if c.reason else "")
            for c in blocked
        )
        raise ProjectError(
            "Sync stopped before writes. Reconcile pending changes; database deletion pushes are not supported yet. "
            + details
        )
    if status == "unbound" and not dry_run:
        save_binding(connection, root)
    return changes

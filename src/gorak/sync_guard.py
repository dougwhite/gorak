"""Target binding and conservative CLI gates while sync execution is migrated."""

import json
import socket
from pathlib import Path
from uuid import uuid4

from .connection import OpenRoadConnection
from .project import ProjectError


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
    connection: OpenRoadConnection,
    root: Path,
    *,
    recover_push: bool = False,
    recover_pull: bool = False,
) -> str:
    if not recover_pull and (root / ".openroad/pull-pending.json").exists():
        raise ProjectError(
            "An interrupted pull requires recovery; inspect .openroad/pull-pending.json and its before-images before continuing"
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


def validate_tracking_health(connection: OpenRoadConnection, root: Path) -> None:
    """Explicit recovery and compilation must preserve managed tracking gates."""
    from uuid import UUID

    from .revision_check import validate_revision_target

    if not connection.revision_generation:
        return
    quarantine = root / ".openroad/revision-quarantine.json"
    if quarantine.exists():
        try:
            blocked = json.loads(quarantine.read_text())["generation"]
            if (
                not isinstance(blocked, str)
                or not UUID(blocked).int
                or str(UUID(blocked)) != blocked
            ):
                raise ValueError
        except (ValueError, KeyError, TypeError) as ex:
            raise ProjectError(
                "Invalid revision quarantine; repair tracking before continuing"
            ) from ex
        if blocked == connection.revision_generation:
            raise ProjectError(
                "Revision generation is quarantined; repair tracking before continuing"
            )
    validate_revision_target(connection)


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

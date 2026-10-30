from pathlib import Path

import pytest

from gorak import sync_guard
from gorak.connection import OpenRoadConnection
from gorak.project import ProjectError


def connection(database: str = "source") -> OpenRoadConnection:
    return OpenRoadConnection("local", "node", database, None)


def test_rebinding_to_another_target_is_rejected(tmp_path: Path) -> None:
    sync_guard.save_binding(connection(), tmp_path)
    with pytest.raises(ProjectError, match="different configured target"):
        sync_guard.binding_status(connection("other"), tmp_path)

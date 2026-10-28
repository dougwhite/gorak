"""Windows metadata queries preserve sharing and close every opened handle."""

import ctypes
from pathlib import Path
from typing import cast

import pytest

from gorak import windows_file_info


@pytest.mark.parametrize("failure", [None, "open", "query"])
def test_native_change_time_handle_lifecycle(
    monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    calls: list[str] = []
    path = Path("baseline.xml")

    def create(*args: object) -> int:
        calls.append("open")
        assert args == (str(path), 0x80, 0x7, None, 3, 0, None)
        return cast(int, ctypes.c_void_p(-1).value) if failure == "open" else 123

    def information(handle: int, kind: int, buffer: object, size: int) -> int:
        calls.append("query")
        assert (handle, kind, size) == (123, 0, 40)
        details = ctypes.cast(
            cast(ctypes.c_void_p, buffer),
            ctypes.POINTER(windows_file_info._FileBasicInfo),
        ).contents
        details.creation_time = 10
        details.last_write_time = 20
        details.change_time = 30
        return 0 if failure == "query" else 1

    def close(handle: int) -> int:
        calls.append("close")
        assert handle == 123
        return 1

    monkeypatch.setattr(
        windows_file_info, "_file_api", lambda: (create, information, close)
    )
    if failure is not None:
        with pytest.raises(OSError):
            windows_file_info.change_time(path)
    else:
        assert windows_file_info.change_time(path) == 30
    assert calls == (["open"] if failure == "open" else ["open", "query", "close"])

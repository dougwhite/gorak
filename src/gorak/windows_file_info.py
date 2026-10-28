"""Read native Windows file change times without reading file contents."""

import ctypes
import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path


class _FileBasicInfo(ctypes.Structure):
    _fields_ = [
        ("creation_time", ctypes.c_int64),
        ("last_access_time", ctypes.c_int64),
        ("last_write_time", ctypes.c_int64),
        ("change_time", ctypes.c_int64),
        ("attributes", ctypes.c_uint32),
    ]


@cache
def _file_api() -> tuple[Callable[..., int], ...]:
    if sys.platform != "win32":
        raise OSError("Windows file information is unavailable")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    create.restype = ctypes.c_void_p
    information = kernel.GetFileInformationByHandleEx
    information.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    information.restype = ctypes.c_int
    close = kernel.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    close.restype = ctypes.c_int
    return create, information, close


def _last_error() -> OSError:
    if sys.platform == "win32":
        return ctypes.WinError(ctypes.get_last_error())
    return OSError("Windows file information is unavailable")


def change_time(path: Path) -> int:
    """Read metadata change time; Python's Windows ctime is creation time."""
    create, information, close = _file_api()
    # FILE_READ_ATTRIBUTES, sharing read/write/delete, OPEN_EXISTING.
    handle = create(str(path), 0x80, 0x7, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise _last_error()
    try:
        details = _FileBasicInfo()
        if not information(handle, 0, ctypes.byref(details), ctypes.sizeof(details)):
            raise _last_error()
        return int(details.change_time)
    finally:
        close(handle)

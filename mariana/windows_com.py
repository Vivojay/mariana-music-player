"""Windows shell and Core Audio COM apartments for native command execution."""
from __future__ import annotations

import ctypes
import sys
from contextlib import contextmanager
from functools import lru_cache
from importlib import import_module


def prepare_command_host():
    if sys.platform == "win32":
        # comtypes initializes the first importing thread and registers its own
        # process-exit cleanup. Let the long-lived host own that initialization.
        # Shell/file operations also work in installations without pycaw.
        try:
            import_module("comtypes")
        except (ImportError, OSError):
            pass


@lru_cache(maxsize=1)
def _ole32():
    # WinDLL returns the raw HRESULT so we can distinguish an apartment owned
    # by another component from a successful, reference-counted initialization.
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoInitializeEx.restype = ctypes.c_int32
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    return ole32


@contextmanager
def command_apartment():
    if sys.platform != "win32":
        yield
        return
    ole32 = _ole32()
    # ShellExecute handlers may require an STA. Core Audio interfaces are
    # obtained, used and released on this same worker before it returns.
    status = ole32.CoInitializeEx(None, 0x2 | 0x4) & 0xffffffff  # STA | DISABLE_OLE1DDE
    if status == 0x80010106:  # RPC_E_CHANGED_MODE: already initialized by the host.
        yield
        return
    if status & 0x80000000:
        raise OSError(f"Windows could not initialize the command thread's COM apartment (0x{status:08X})")
    try:
        yield
    finally:
        # Both S_OK and S_FALSE add a COM initialization reference.
        ole32.CoUninitialize()

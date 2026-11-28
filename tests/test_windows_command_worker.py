"""Exercise the Windows worker contract without changing a machine's real audio or shell."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mariana import platform, windows_audio, windows_com
from mariana.terminal_io import TerminalIO, current_session


class FakeOle32:
    def __init__(self, preexisting=0, failure=None):
        self.preexisting = preexisting
        self.failure = failure
        self.local = threading.local()
        self.calls = []

    @property
    def depth(self):
        return getattr(self.local, "depth", self.preexisting)

    def CoInitializeEx(self, reserved, flags):
        assert reserved is None and flags == 6
        self.calls.append(("init", threading.get_ident()))
        if self.failure is not None:
            return self.failure
        old = self.depth
        self.local.depth = old + 1
        return 1 if old else 0

    def CoUninitialize(self):
        assert self.depth > 0
        self.calls.append(("release", threading.get_ident()))
        self.local.depth = self.depth - 1


def host(monkeypatch, ole):
    main_thread = threading.get_ident()
    imports = []
    monkeypatch.setattr(windows_com.sys, "platform", "win32")
    monkeypatch.setattr(windows_com, "import_module", lambda name: imports.append((name, threading.get_ident())))
    monkeypatch.setattr(windows_com, "_ole32", lambda: ole)
    io = TerminalIO(lambda: None, lambda _: None, lambda: None)
    assert imports == [("comtypes", main_thread)]
    return io


def test_windows_command_worker_owns_volume_shell_and_releases_after_success_or_cancel(monkeypatch, tmp_path):
    ole = FakeOle32()
    io = host(monkeypatch, ole)
    observed = []

    def check(label):
        assert current_session() is io and ole.depth == 1
        observed.append((label, threading.get_ident()))

    class Volume:
        def GetMasterVolumeLevelScalar(self):
            check("get")
            return 0.42

        def SetMasterVolumeLevelScalar(self, value, target):
            assert value == 0.42 and target is None
            check("set")

    def endpoint():
        check("endpoint")
        return Volume()

    def reveal(argv, **stdio):
        assert argv == ["explorer", "/select,", str(tmp_path.resolve())]
        assert stdio == dict.fromkeys(("stdin", "stdout", "stderr"), platform.subprocess.DEVNULL)
        check("reveal")

    monkeypatch.setattr(windows_audio, "endpoint_volume", endpoint)
    monkeypatch.setattr(platform.os, "startfile", lambda path: check("open"), raising=False)
    monkeypatch.setattr(platform.subprocess, "Popen", reveal)

    def first():
        with io.worker():
            assert platform.get_master_volume() == 42
            platform.set_master_volume(42)
            platform.open_path(tmp_path)
            platform.reveal_path(tmp_path)
        assert current_session() is None and ole.depth == 0

    def second():
        with pytest.raises(KeyboardInterrupt), io.worker(), io.worker():
            assert current_session() is io and ole.depth == 2
            raise KeyboardInterrupt()
        assert current_session() is None and ole.depth == 0

    with ThreadPoolExecutor(max_workers=1) as workers:
        workers.submit(first).result(timeout=5)
        workers.submit(second).result(timeout=5)
    assert [label for label, _ in observed] == ["endpoint", "get", "endpoint", "set", "open", "reveal"]
    thread = observed[0][1]
    assert thread != threading.get_ident()
    assert ole.calls == [(op, thread) for op in ["init", "release", "init", "init", "release", "release"]]


@pytest.mark.parametrize(("status", "runs"), [(0x80010106, True), (-2147417850, True), (0x8007000E, False)])
def test_existing_incompatible_apartment_and_failed_initialization_are_never_released(monkeypatch, status, runs):
    ole = FakeOle32(preexisting=int(runs), failure=status)
    io = host(monkeypatch, ole)
    def run():
        if runs:
            with io.worker():
                assert current_session() is io and ole.depth == 1
        else:
            with pytest.raises(OSError, match="8007000E"), io.worker():
                pytest.fail("Command ran without successfully entering the worker")
        assert current_session() is None
    with ThreadPoolExecutor(max_workers=1) as workers:
        workers.submit(run).result(timeout=5)
    assert [op for op, _ in ole.calls] == ["init"]


def test_optional_pycaw_is_not_needed_for_the_windows_shell(monkeypatch):
    ole = FakeOle32()
    monkeypatch.setattr(windows_com.sys, "platform", "win32")
    monkeypatch.setattr(windows_com, "import_module", lambda _: (_ for _ in ()).throw(ImportError("optional")))
    monkeypatch.setattr(windows_com, "_ole32", lambda: ole)
    io = TerminalIO(lambda: None, lambda _: None, lambda: None)
    with io.worker():
        assert ole.depth == 1
    assert ole.depth == 0


def test_other_platforms_never_load_windows_libraries(monkeypatch):
    monkeypatch.setattr(windows_com.sys, "platform", "linux")
    monkeypatch.setattr(windows_com, "import_module", lambda _: pytest.fail("Windows dependency was loaded"))
    monkeypatch.setattr(windows_com, "_ole32", lambda: pytest.fail("ole32 was loaded"))
    io = TerminalIO(lambda: None, lambda _: None, lambda: None)
    with io.worker():
        assert current_session() is io

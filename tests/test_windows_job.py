"""Optional native module availability and Windows job handle ownership."""

import gc
import sys
import weakref
from types import SimpleNamespace

import pytest

from mariana import playback


def test_non_windows_job_never_loads_native_apis(monkeypatch):
    monkeypatch.setattr(playback, "_is_windows", lambda: False)
    monkeypatch.setitem(sys.modules, "win32job", None)
    monkeypatch.setitem(sys.modules, "win32api", None)

    def unexpected(_name):
        pytest.fail("A non-Windows job attempted to load a native API")

    monkeypatch.setattr(playback.importlib, "import_module", unexpected)
    job = playback.WindowsJob(SimpleNamespace())
    assert job.handle is None
    job.close()


def test_windows_job_without_optional_module_is_best_effort(monkeypatch):
    monkeypatch.setattr(playback, "_is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32job", None)
    job = playback.WindowsJob(SimpleNamespace(_handle=7))
    assert job.handle is None
    job.close()


def test_windows_job_close_without_optional_api_releases_its_reference(monkeypatch):
    released = []

    class OwnedHandle:
        def __del__(self):
            released.append(True)

    job = object.__new__(playback.WindowsJob)
    job.handle = OwnedHandle()
    monkeypatch.setitem(sys.modules, "win32api", None)
    job.close()
    gc.collect()
    assert job.handle is None and released == [True]
    job.close()
    assert released == [True]


@pytest.mark.parametrize("failure", ["query", "set", "assign"])
def test_failed_windows_job_setup_releases_the_owned_native_handle(monkeypatch, failure):
    released, owners = [], []

    class OwnedHandle:
        # PyHANDLE owns and closes its native handle when the object is released.
        def __del__(self):
            released.append(True)

    def create(*_args):
        handle = OwnedHandle()
        owners.append(weakref.ref(handle))
        return handle

    def operation(name, result=None):
        def call(*_args):
            if name == failure:
                raise OSError("Native job setup failed")
            return result
        return call

    fake_job = SimpleNamespace(
        CreateJobObject=create,
        QueryInformationJobObject=operation("query", {"BasicLimitInformation": {"LimitFlags": 0}}),
        SetInformationJobObject=operation("set"),
        AssignProcessToJobObject=operation("assign"),
        JobObjectExtendedLimitInformation=1,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=2,
    )
    monkeypatch.setattr(playback, "_is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32job", fake_job)
    job = playback.WindowsJob(SimpleNamespace(_handle=7))
    gc.collect()
    assert job.handle is None
    assert len(owners) == 1 and owners[0]() is None
    assert released == [True]
    job.close()
    assert released == [True]

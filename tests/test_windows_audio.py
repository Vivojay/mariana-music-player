"""Regressions for minimal, bounded Core Audio endpoint access."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from mariana import windows_audio


@pytest.fixture
def core_audio(monkeypatch):
    monkeypatch.setattr(windows_audio.sys, "platform", "win32")
    modules = {}
    for name in ("comtypes", "pycaw", "pycaw.api", "pycaw.api.mmdeviceapi",
                 "pycaw.api.mmdeviceapi.depend", "pycaw.api.mmdeviceapi.depend.structures",
                 "pycaw.api.endpointvolume", "pycaw.constants"):
        modules[name] = ModuleType(name)
        monkeypatch.setitem(sys.modules, name, modules[name])
    modules["comtypes"].GUID = str
    modules["comtypes"].CLSCTX_INPROC_SERVER = 1
    modules["comtypes"].CLSCTX_ALL = 23
    modules["pycaw.api.mmdeviceapi"].IMMDeviceEnumerator = object()
    modules["pycaw.api.mmdeviceapi.depend.structures"].PROPERTYKEY = SimpleNamespace
    modules["pycaw.api.endpointvolume"].IAudioEndpointVolume = SimpleNamespace(_iid_="volume")
    constants = modules["pycaw.constants"]
    constants.CLSID_MMDeviceEnumerator = "enumerator"
    constants.EDataFlow = SimpleNamespace(eRender=SimpleNamespace(value=0))
    constants.ERole = SimpleNamespace(eMultimedia=SimpleNamespace(value=1))
    constants.STGM = SimpleNamespace(STGM_READ=SimpleNamespace(value=0))
    return modules


@pytest.mark.parametrize("broken_value", [False, True])
def test_endpoint_reads_only_friendly_name_and_releases_value(core_audio, broken_value):
    calls = []

    def read():
        if broken_value:
            raise OSError("unreadable name")
        return " Speakers "

    value = SimpleNamespace(GetValue=read, clear=lambda: calls.append("clear"))

    def get_value(key):
        assert key.fmtid == "{a45c254e-df1c-4efd-8020-67d146a850e0}" and key.pid == 14
        calls.append("friendly-name")
        return value

    # No enumeration API is supplied: unrelated driver properties must not be read.
    store = SimpleNamespace(GetValue=get_value)
    endpoint = SimpleNamespace(GetId=lambda: " endpoint ", OpenPropertyStore=lambda mode: store)
    if broken_value:
        with pytest.raises(OSError, match="unreadable name"):
            windows_audio.endpoint_identity(endpoint)
    else:
        assert windows_audio.endpoint_identity(endpoint) == ("endpoint", "Speakers")
    assert calls == ["friendly-name", "clear"]


def test_volume_activation_does_not_enumerate_properties(core_audio):
    calls = []
    volume = object()
    interface = SimpleNamespace(QueryInterface=lambda _type: volume)
    endpoint = SimpleNamespace(Activate=lambda *args: calls.append(args) or interface)
    enumerator = SimpleNamespace(GetDefaultAudioEndpoint=lambda *args: calls.append(args) or endpoint)
    core_audio["comtypes"].CoCreateInstance = lambda *args: enumerator
    assert windows_audio.endpoint_volume() is volume
    assert calls == [(0, 1), ("volume", 23, None)]
    enumerator.GetDefaultAudioEndpoint = lambda *_args: None
    assert windows_audio.endpoint_volume() is None


def test_legacy_volume_adapter_uses_minimal_endpoint(monkeypatch):
    from beta import master_volume_control

    volume = object()
    monkeypatch.setattr(windows_audio, "endpoint_volume", lambda: volume)
    assert master_volume_control.device_refresh() is volume
    monkeypatch.setattr(windows_audio, "endpoint_volume", lambda: None)
    with pytest.raises(RuntimeError, match="default audio endpoint"):
        master_volume_control.device_refresh()


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_core_audio_boundary_rejects_unsupported_platforms_before_import(monkeypatch, platform):
    monkeypatch.setattr(windows_audio.sys, "platform", platform)
    monkeypatch.setitem(sys.modules, "comtypes", None)
    monkeypatch.setitem(sys.modules, "pycaw", None)
    for action in (windows_audio.default_endpoint, windows_audio.endpoint_volume,
                   lambda: windows_audio.endpoint_identity(object())):
        with pytest.raises(ImportError, match="unavailable on this platform"):
            action()

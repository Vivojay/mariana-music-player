import sys
from types import ModuleType, SimpleNamespace
from typing import ClassVar

import pytest

from mariana import output_devices
from mariana.output_devices import OutputDeviceError, OutputDeviceInfo, default_output_device
from mariana.playback import PlaybackController
from mariana.supervisor import PlaybackSupervisor


class AudioBackend:
    def __init__(self, devices, hostapis, default_index=0):
        self.devices = devices
        self.hostapis = hostapis
        self.default_index = default_index

    def query_devices(self, index=None, kind=None):
        if kind == "output":
            result = dict(self.devices[self.default_index])
            result["index"] = self.default_index
            return result
        if index is not None:
            return self.devices[index]
        return self.devices

    def query_hostapis(self, index):
        return {"name": self.hostapis[index]}


DEVICES = [
    {"name": "Microsoft Sound Mapper - Output", "hostapi": 0, "max_output_channels": 2},
    {"name": "Headphones (Old Device)", "hostapi": 0, "max_output_channels": 2},
    {"name": "JBL FLIP 5 Stereo", "hostapi": 1, "max_output_channels": 2},
    {"name": "Microphone", "hostapi": 1, "max_output_channels": 0},
]


def test_windows_core_audio_name_and_endpoint_are_authoritative(monkeypatch):
    audio = AudioBackend(DEVICES, ["MME", "Windows WASAPI"], default_index=1)
    monkeypatch.setattr(
        output_devices,
        "_windows_default_endpoint",
        lambda: ("endpoint-jbl", "Speakers (JBL Flip 5 Stereo)"),
    )

    selected = default_output_device(audio)

    assert selected.key == "endpoint-jbl"
    assert selected.name == "Speakers (JBL Flip 5 Stereo)"
    assert selected.index == 2
    assert selected.hostapi == "Windows WASAPI"


def test_windows_new_bluetooth_endpoint_uses_system_mapper(monkeypatch):
    audio = AudioBackend(DEVICES[:2], ["MME"], default_index=1)
    monkeypatch.setattr(
        output_devices,
        "_windows_default_endpoint",
        lambda: ("endpoint-new", "JBL Flip 5"),
    )

    selected = default_output_device(audio)

    assert selected.name == "JBL Flip 5"
    assert selected.index == 0
    assert selected.portaudio_name == "Microsoft Sound Mapper - Output"


def test_portaudio_default_is_cross_platform_fallback(monkeypatch):
    audio = AudioBackend(DEVICES, ["MME", "Core Audio"], default_index=2)
    monkeypatch.setattr(output_devices, "_windows_default_endpoint", lambda: None)

    selected = default_output_device(audio)

    assert selected.name == "JBL FLIP 5 Stereo"
    assert selected.index == 2
    assert selected.hostapi == "Core Audio"


def test_output_discovery_reports_enumeration_and_missing_device_errors(monkeypatch):
    monkeypatch.setattr(output_devices, "_windows_default_endpoint", lambda: None)
    with pytest.raises(OutputDeviceError, match="No enabled"):
        default_output_device(AudioBackend([], []))
    broken = SimpleNamespace(query_devices=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("driver")))
    with pytest.raises(OutputDeviceError, match="enumeration failed"):
        default_output_device(broken)


def test_device_score_and_endpoint_fallback_branches(monkeypatch):
    assert output_devices._device_score("", "Device", "MME") == 0
    assert output_devices._device_score("Speakers", "Speakers", "DirectSound") > 80
    assert output_devices._device_score("JBL", "JBL Flip", "DirectSound") > 40
    assert output_devices._device_score("Speakers", "Headphones", "MME") >= 0

    monkeypatch.setattr(output_devices.os, "name", "posix")
    assert output_devices._windows_default_endpoint() is None


def test_windows_endpoint_empty_and_failure_are_safe(monkeypatch):
    audio_utilities = SimpleNamespace()
    comtypes = ModuleType("comtypes")
    comtypes.CoInitialize = lambda: None
    comtypes.CoUninitialize = lambda: None
    pycaw_package = ModuleType("pycaw")
    pycaw_module = ModuleType("pycaw.pycaw")
    pycaw_module.AudioUtilities = audio_utilities
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setitem(sys.modules, "pycaw", pycaw_package)
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", pycaw_module)

    monkeypatch.setattr(output_devices.os, "name", "nt")
    monkeypatch.setattr(
        audio_utilities,
        "GetSpeakers",
        staticmethod(lambda: SimpleNamespace(FriendlyName="", id="")),
        raising=False,
    )
    assert output_devices._windows_default_endpoint() is None
    monkeypatch.setattr(
        audio_utilities,
        "GetSpeakers",
        staticmethod(lambda: (_ for _ in ()).throw(OSError("Core Audio unavailable"))),
    )
    assert output_devices._windows_default_endpoint() is None


def test_hostapi_and_default_query_failures_are_typed(monkeypatch):
    class Backend:
        def query_devices(self, kind=None):
            if kind:
                raise OSError("default disappeared")
            return [{"name": "Output", "hostapi": 0, "max_output_channels": 2}]

        def query_hostapis(self, _index):
            raise OSError("host unavailable")

    backend = Backend()
    assert output_devices._hostapi_name(backend, 0) == ""
    monkeypatch.setattr(output_devices, "_windows_default_endpoint", lambda: None)
    with pytest.raises(OutputDeviceError, match="system default"):
        default_output_device(backend)


def test_cross_platform_default_without_explicit_index(monkeypatch):
    class Backend:
        def query_devices(self, kind=None):
            return {"name": "Default Output", "hostapi": 0, "max_output_channels": 2}

        def query_hostapis(self, _index):
            return {"name": "Core Audio"}

    monkeypatch.setattr(output_devices, "_windows_default_endpoint", lambda: None)
    selected = default_output_device(Backend())
    assert selected.index is None and selected.name == "Default Output"


class Stream:
    instances: ClassVar[list["Stream"]] = []

    def __init__(self, **kwargs):
        self.device = kwargs["device"]
        self.started = self.stopped = self.closed = False
        self.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True

    @property
    def active(self):
        return self.started and not self.stopped and not self.closed


def test_supervisor_reopens_stream_when_os_default_endpoint_changes():
    devices = [
        OutputDeviceInfo("headphones", "Headphones", 3, "Headphones", "Windows WASAPI"),
        OutputDeviceInfo("jbl", "JBL Flip 5", 7, "JBL Flip 5", "Windows WASAPI"),
    ]
    current = {"value": devices[0]}
    Stream.instances.clear()
    controller = PlaybackController(
        output_factory=Stream,
        output_device_provider=lambda: current["value"],
    )
    supervisor = PlaybackSupervisor(controller)
    controller._ensure_output()
    original = Stream.instances[-1]

    current["value"] = devices[1]
    assert supervisor._sync_output_device()

    assert original.stopped and original.closed
    assert Stream.instances[-1].device == 7
    assert controller.active_output_device == devices[1]
    assert controller.snapshot().output_device == "JBL Flip 5"
    assert supervisor.metrics["output_device_changes"] == 1
    assert not supervisor._sync_output_device()
    Stream.instances[-1].stopped = True
    assert supervisor._sync_output_device()
    assert Stream.instances[-1].device == 7
    assert supervisor.metrics["output_recoveries"] == 2
    assert supervisor.metrics["output_device_changes"] == 1
    supervisor.close()


def test_output_stream_replacement_failure_and_noop_paths():
    device = OutputDeviceInfo("device", "Device", 1, "Device", "test")
    stream = Stream(device=1)
    stream.start()
    controller = PlaybackController(output_factory=Stream, output_device_provider=lambda: device)
    controller._stream = stream
    controller._output_device = device

    controller._replace_output(device)
    assert controller._stream is stream and not stream.stopped
    controller.clear_prefetch()
    assert controller.output_stream_active

    class BrokenStream(Stream):
        def start(self):
            raise OSError("device vanished")

    controller.output_factory = BrokenStream
    with pytest.raises(OSError, match="vanished"):
        controller.recover_output(device)
    assert BrokenStream.instances[-1].stopped and BrokenStream.instances[-1].closed
    assert not controller.output_stream_active
    controller.report_output_error("device unavailable")
    assert controller.snapshot().error == "device unavailable"
    controller._close_output_stream(None)


def test_output_factory_failure_before_stream_creation_and_close_finally():
    device = OutputDeviceInfo("device", "Device", 1, "Device", "test")
    controller = PlaybackController(
        output_factory=lambda **_kwargs: (_ for _ in ()).throw(OSError("open failed")),
        output_device_provider=lambda: device,
    )
    with pytest.raises(OSError, match="open failed"):
        controller._ensure_output()

    calls = []

    class StopFailure:
        def stop(self):
            calls.append("stop")
            raise OSError("stop failed")

        def close(self):
            calls.append("close")

    with pytest.raises(OSError, match="stop failed"):
        controller._close_output_stream(StopFailure())
    assert calls == ["stop", "close"]

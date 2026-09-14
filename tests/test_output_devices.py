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


@pytest.mark.parametrize(("endpoint", "stale"), [
    ("Speakers (New Bluetooth Speaker)", "Speakers (Old Bluetooth Speaker)"),
    ("Speakers (Realtek(R) Audio)", "Speakers (USB Audio)"),
    ("Headphones (WH-1000XM5)", "Headphones (WH-1000XM4)"),
])
def test_similarly_named_stale_endpoint_is_not_mislabelled_as_current(monkeypatch, endpoint, stale):
    audio = AudioBackend([
        DEVICES[0], {"name": stale, "hostapi": 1, "max_output_channels": 2},
    ], ["MME", "Windows WASAPI"], default_index=1)
    monkeypatch.setattr(output_devices, "_windows_default_endpoint", lambda: ("new-endpoint", endpoint))
    selected = default_output_device(audio)
    assert selected.index == 0
    assert selected.key == "new-endpoint"
    assert selected.name == endpoint
    assert selected.portaudio_name == "Microsoft Sound Mapper - Output"


def test_unmatched_endpoint_without_live_mapper_waits_instead_of_opening_other_device(monkeypatch):
    audio = AudioBackend([DEVICES[1]], ["MME"])
    monkeypatch.setattr(output_devices, "_windows_default_endpoint", lambda: ("new", "New USB DAC"))
    with pytest.raises(OutputDeviceError, match="no confirmed playback route"):
        default_output_device(audio)


def test_duplicate_native_endpoint_names_use_live_mapper(monkeypatch):
    output = {"name": "USB DAC", "hostapi": 1, "max_output_channels": 2}
    audio = AudioBackend([DEVICES[0], output, dict(output)], ["MME", "Windows WASAPI"])
    monkeypatch.setattr(output_devices, "_windows_default_endpoint", lambda: ("new", "USB DAC"))
    assert default_output_device(audio).index == 0
    audio.devices = [output, dict(output)]
    with pytest.raises(OutputDeviceError, match="no confirmed playback route"):
        default_output_device(audio)


def test_route_matching_requires_complete_non_generic_device_tokens():
    assert output_devices._endpoint_matches_route("Speakers (JBL Flip 5 Stereo)", "JBL FLIP 5 Stereo")
    assert output_devices._endpoint_matches_route("Speakers", "Speakers")
    assert not output_devices._endpoint_matches_route("Speakers", "Headphones")
    assert not output_devices._endpoint_matches_route("", "Headphones")
    assert not output_devices._endpoint_matches_route("Headphones (WH-1000XM5)", "Headphones (WH-1000XM)")


def test_windows_failed_explicit_route_can_select_live_system_mapper(monkeypatch):
    audio = AudioBackend(DEVICES, ["MME", "Windows WASAPI"])
    monkeypatch.setattr(output_devices, "_windows_default_endpoint", lambda: ("endpoint", "JBL FLIP 5 Stereo"))
    explicit = default_output_device(audio)
    fallback = default_output_device(audio, prefer_system_mapper=True)
    assert explicit.index == 2 and fallback.index == 0
    assert explicit.key == fallback.key and explicit.name == fallback.name


def test_output_native_route_failure_uses_mapper_without_global_audio_reset(monkeypatch):
    from mariana import playback

    explicit = OutputDeviceInfo("endpoint", "Speaker", 2, "Speaker", "WASAPI", "endpoint")
    mapper = OutputDeviceInfo("endpoint", "Speaker", 0, "Mapper", "MME", "endpoint")
    attempts = []

    def factory(**kwargs):
        attempts.append(kwargs["device"])
        if kwargs["device"] == 2:
            raise OSError("stale explicit route")
        return Stream(**kwargs)

    monkeypatch.setattr(playback.sounddevice, "OutputStream", factory)
    monkeypatch.setattr(playback, "default_output_device", lambda **kwargs: mapper if kwargs else explicit)
    controller = PlaybackController()
    controller._ensure_output()
    assert attempts == [2, 0]
    assert controller.active_output_device == mapper and controller.output_stream_active
    controller.close()


def test_invalidated_old_stream_close_does_not_block_replacement():
    class Invalidated(Stream):
        @property
        def active(self):
            raise OSError("device status invalidated")

        def stop(self):
            raise OSError("device invalidated")

    device = OutputDeviceInfo("endpoint", "Speaker", 1, "Speaker", "test")
    old = Invalidated(device=1)
    controller = PlaybackController(output_factory=Stream, output_device_provider=lambda: device)
    controller._stream = old
    assert not controller.output_stream_active
    controller.recover_output()
    assert old.closed
    assert controller.output_stream_active
    controller.close()


def test_inactive_same_device_stream_is_reopened_on_new_play():
    device = OutputDeviceInfo("endpoint", "Speaker", 1, "Speaker", "test")
    controller = PlaybackController(output_factory=Stream, output_device_provider=lambda: device)
    controller._ensure_output()
    old = controller._stream
    old.stop()
    controller._ensure_output()
    assert old.closed and controller._stream is not old and controller.output_stream_active
    controller.close()


def test_replacement_start_and_cleanup_failure_preserves_open_error():
    class Broken(Stream):
        def start(self):
            raise OSError("open error")

        def stop(self):
            raise OSError("cleanup error")

    controller = PlaybackController(output_factory=Broken)
    with pytest.raises(OSError, match="open error"):
        controller.recover_output()
    assert Broken.instances[-1].closed
    assert not controller.output_stream_active
    controller.close()


def test_native_fallback_does_not_retry_the_same_route(monkeypatch):
    from mariana import playback

    device = OutputDeviceInfo("endpoint", "Mapper", 0, "Mapper", "MME", "endpoint")
    attempts = []

    def broken(**kwargs):
        attempts.append(kwargs["device"])
        raise OSError("unavailable")

    monkeypatch.setattr(playback.sounddevice, "OutputStream", broken)
    monkeypatch.setattr(playback, "default_output_device", lambda **_: device)
    controller = PlaybackController()
    with pytest.raises(OSError, match="unavailable"):
        controller.recover_output()
    assert attempts == [0]
    controller.close()


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

    outputs = [
        (0, {"name": "USB DAC"}, "Core Audio"),
        (1, {"name": "Primary Sound Driver"}, "MME"),
    ]
    assert output_devices._system_mapper(outputs) == outputs[1]
    assert output_devices._system_mapper(outputs[:1]) is None


def test_windows_endpoint_empty_and_failure_are_safe(monkeypatch):
    from mariana import windows_audio

    comtypes = ModuleType("comtypes")
    lifetime = []
    comtypes.CoInitialize = lambda: lifetime.append("open")
    comtypes.CoUninitialize = lambda: lifetime.append("close")
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setattr(windows_audio, "default_endpoint", lambda: object())

    monkeypatch.setattr(output_devices.os, "name", "nt")
    monkeypatch.setattr(
        windows_audio, "endpoint_identity", lambda _endpoint: ("endpoint-id", "Speakers"),
    )
    assert output_devices._windows_default_endpoint() == ("endpoint-id", "Speakers")
    monkeypatch.setattr(
        windows_audio, "endpoint_identity", lambda _endpoint: ("", ""),
    )
    assert output_devices._windows_default_endpoint() is None
    monkeypatch.setattr(
        windows_audio, "endpoint_identity",
        lambda _endpoint: (_ for _ in ()).throw(OSError("Core Audio unavailable")),
    )
    assert output_devices._windows_default_endpoint() is None
    assert lifetime == ["open", "close"] * 3


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


def test_output_recovery_stopped_during_open_does_not_publish_stale_stream():
    from mariana.playback import PlaybackError

    device = OutputDeviceInfo("device", "Device", 1, "Device", "test")
    opened = []

    def factory(**kwargs):
        stream = Stream(**kwargs)
        opened.append(stream)
        controller.stop()  # Stop wins while the native open was pending.
        return stream

    controller = PlaybackController(output_factory=factory, output_device_provider=lambda: device)
    with pytest.raises(PlaybackError, match="replaced"):
        controller.recover_output()
    assert len(opened) == 1
    assert opened[0].closed and opened[0].stopped
    assert controller._stream is None
    assert not controller.output_stream_active
    controller.close()


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

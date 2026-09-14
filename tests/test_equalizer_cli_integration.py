"""EQ command wiring without the desktop panel or unrelated application state."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn, cast

import numpy as np
import pytest

import main
from config_manager import load_user_settings, save_user_settings
from mariana.command_catalog import CommandRisk, serialize_command_catalog
from mariana.equalizer import EqualizerService
from mariana.models import MediaRef, MediaSource, PlaybackState
from mariana.playback import DecoderSession, PlaybackController


def _unexpected_output(**_kwargs) -> NoReturn:
    raise AssertionError("EQ control must not open an audio output")


@pytest.fixture
def eq_runtime(monkeypatch, tmp_path):
    controller = PlaybackController(output_factory=_unexpected_output)
    monkeypatch.setattr(main.vas, "controller", controller)
    monkeypatch.setattr(main, "SETTINGS", deepcopy(main.SETTINGS))
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=tmp_path / "settings.yml"))
    events = []
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(emit=lambda *args: events.append(args)))
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    service = EqualizerService(lambda: main.vas.controller.equalizer, persist=main._persist_equalizer_configuration)
    monkeypatch.setattr(main, "EQUALIZER", service)
    return controller, service, events


@pytest.mark.parametrize("arguments", [
    ["band", "1khz", "nan"], ["band", "1khz", "inf"], ["band", "1khz", "12.1"],
    ["band", "123hz", "2"], ["preamp", "-36.1"], ["preamp", "12.1"],
    ["preamp", "-inf"], ["on", "extra"], ["preset", "save", "../private"],
])
def test_invalid_cli_values_never_persist_publish_or_emit(eq_runtime, arguments):
    _controller, service, events = eq_runtime
    main.eq_command(["on"])
    before_settings = deepcopy(main.SETTINGS)
    before_status = service.status()
    before_file = main.RUNTIME_PATHS.settings.read_bytes()
    before_events = list(events)

    with pytest.raises(ValueError):
        main.eq_command(arguments)

    assert before_settings == main.SETTINGS
    assert service.status() == before_status
    assert main.RUNTIME_PATHS.settings.read_bytes() == before_file
    assert events == before_events


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_reset_preserves_bypass_and_saved_presets(eq_runtime, enabled):
    _controller, service, _events = eq_runtime
    main.eq_command(["on" if enabled else "off"])
    main.eq_command(["band", "1khz", "6"])
    main.eq_command(["preamp", "-9"])
    main.process('eq preset save "Quiet listening"')

    status = main.eq_command(["reset"])

    assert status["enabled"] is enabled
    assert status["bands"] == [0] * 10 and status["preamp"] == 0
    assert "Quiet listening" in service.presets
    main.process('eq preset apply "Quiet listening"')
    assert service.settings.enabled is enabled
    assert service.settings.bands[5] == 6 and service.settings.preamp == -9
    main.process('eq preset delete "Quiet listening"')
    assert "Quiet listening" not in service.presets


def test_atomic_replace_failure_keeps_file_service_settings_and_events(eq_runtime, monkeypatch):
    _controller, service, events = eq_runtime
    main.eq_command(["off"])
    before_file = main.RUNTIME_PATHS.settings.read_bytes()
    before_settings = deepcopy(main.SETTINGS)
    before_status = service.status()
    before_events = list(events)
    monkeypatch.setattr("config_manager.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("private/path")))

    with pytest.raises(ValueError, match=r"^Could not save equalizer settings$"):
        main.eq_command(["on"])

    assert main.RUNTIME_PATHS.settings.read_bytes() == before_file
    assert before_settings == main.SETTINGS and service.status() == before_status
    assert events == before_events
    assert not list(main.RUNTIME_PATHS.settings.parent.glob(".settings.yml.*.tmp"))


def test_factory_defaults_add_eq_without_overwriting_user_configuration(tmp_path):
    defaults = Path(main.__file__).parent / "settings" / "settings.yml.default"
    path = tmp_path / "settings.yml"
    save_user_settings({"visible": False}, path)
    fresh = load_user_settings(path, defaults)
    assert fresh["equalizer"] == {"enabled": False, "bands": [0] * 10, "preamp": 0, "presets": {}}
    assert fresh["visible"] is False
    custom = {"enabled": True, "bands": [3] * 10, "preamp": -12, "presets": {}}
    save_user_settings({"equalizer": custom}, path)
    assert load_user_settings(path, defaults)["equalizer"] == custom


def test_settings_help_and_catalog_expose_only_supported_eq_forms(eq_runtime, monkeypatch):
    printed = []
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: printed.append(str(value)))
    main.help_command(["settings"])
    assert "eq" in "\n".join(printed)
    assert 'eq preset save "Quiet listening"' in "\n".join(printed)
    rows = {row["canonical"]: row for row in serialize_command_catalog() if str(row["key"]).startswith("eq")}
    assert set(rows) == {
        "eq", "eq on", "eq off", "eq band", "eq preamp", "eq reset",
        "eq preset list", "eq preset apply", "eq preset save", "eq preset delete",
    }
    assert rows["eq"]["risk"] == rows["eq preset list"]["risk"] == CommandRisk.READ_ONLY.value
    assert rows["eq preset delete"]["risk"] == CommandRisk.DESTRUCTIVE.value
    assert rows["eq band"]["forms"][0]["argument_kinds"] == ("frequency", "gain-db")


def test_runtime_refresh_reapplies_eq_without_artwork_service(eq_runtime, monkeypatch):
    original, service, _events = eq_runtime
    main.eq_command(["on"])
    main.eq_command(["preamp", "-6"])
    settings = deepcopy(main.SETTINGS)
    replacement = PlaybackController(output_factory=_unexpected_output)
    monkeypatch.delattr(main, "ARTWORK", raising=False)
    monkeypatch.setattr(main, "load_user_settings", lambda: settings)
    monkeypatch.setattr(main.YT_query, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(main.vas, "configure", lambda **_kwargs: setattr(main.vas, "controller", replacement))
    monkeypatch.setattr(main, "IDENTITY", SimpleNamespace(fpcalc_bin=None))
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace(ffmpeg_bin=None, fpcalc_bin=None, rsgain=None))
    monkeypatch.setattr(main, "check_runtime", lambda *_args: SimpleNamespace(errors=[]))
    for name in ("MEDIA_TOOLS", "RUNTIME_REPORT", "FATAL_ERROR_INFO", "AUTOPLAY_ENABLED", "visible", "loglevel", "DEFAULT_EDITOR"):
        monkeypatch.setattr(main, name, getattr(main, name))

    main.refresh_runtime_configuration()

    assert main.vas.controller is replacement and replacement is not original
    for _ in range(40):
        output = replacement.equalizer.process(np.full((512, 2), .25))
    np.testing.assert_allclose(output, .25 * 10 ** (-6 / 20))
    assert service.settings.preamp == -6
    main.eq_command(["preamp", "-12"])
    for _ in range(40):
        output = replacement.equalizer.process(np.full((512, 2), .25))
    np.testing.assert_allclose(output, .25 * 10 ** (-12 / 20))


def test_cli_eq_changes_local_pcm_not_program_bus_or_recorded_gain(eq_runtime):
    controller, _service, _events = eq_runtime
    media = MediaRef(MediaSource.LOCAL, "private/track.flac", duration=120)
    active = SimpleNamespace(
        media=media, position=10.0, buffered_seconds=1.0, eof=False,
        program_gain=2.0, program_gain_db=6.020599913279624,
        read=lambda frames: np.full((frames, 2), .25, dtype=np.float32).tobytes(),
    )
    controller._active = cast(DecoderSession, active)
    controller._state = PlaybackState.PLAYING
    captured = []
    controller.add_program_sink(lambda samples, _frames: captured.append(np.array(samples, copy=True)))
    before = controller.recipe_capture_snapshot()
    main.eq_command(["on"])
    main.eq_command(["preamp", "-12"])
    output = np.empty((512, 2), dtype=np.float32)

    for _ in range(40):
        controller._audio_callback(output, 512, None, None)

    np.testing.assert_allclose(captured, .5)
    np.testing.assert_allclose(output, .5 * 10 ** (-12 / 20), rtol=1e-6)
    assert controller._active is active and controller.snapshot().media is media
    assert controller.recipe_capture_snapshot() == before
    assert active.program_gain_db == before.program_gain_db
    assert active.position == 10.0

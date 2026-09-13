from dataclasses import replace

import numpy as np
import pytest

from mariana.equalizer import (
    FACTORY_PRESETS,
    FREQUENCIES,
    EqualizerProcessor,
    EqualizerService,
    EqualizerSettings,
    coefficients,
    command_intent,
    frequency,
    response,
)


def settle(processor):
    for _ in range(len(processor.ramp) // 512 + 2):
        processor.process(np.zeros((512, 2)))


def test_flat_bypass_and_block_state_are_exact():
    rng = np.random.default_rng(41)
    samples = rng.normal(0, .1, (4096, 2))
    engine = EqualizerProcessor()
    assert engine.process(samples) is samples
    settings = EqualizerSettings(True)
    engine.submit(engine.prepare(settings))
    settle(engine)
    np.testing.assert_array_equal(engine.process(samples), samples)
    settings = replace(settings, bands=(6.,) * 10, preamp=-24)
    engine.submit(engine.prepare(settings))
    settle(engine)
    whole = engine.process(samples)
    engine.reset()
    split = np.concatenate([engine.process(part) for part in np.array_split(samples, 8)])
    np.testing.assert_allclose(whole, split, atol=1e-12)
    engine.submit(engine.prepare(replace(settings, enabled=False)))
    settle(engine)
    assert engine.process(samples) is samples


@pytest.mark.parametrize("sample_rate", [8000, 16000, 22050, 44100, 48000, 96000, 192000])
@pytest.mark.parametrize("db", [-12., 12.])
def test_measured_response_stereo_and_extreme_stability(sample_rate, db):
    settings = EqualizerSettings(True, (db,) * 10, -24)
    engine = EqualizerProcessor(sample_rate)
    engine.submit(engine.prepare(settings))
    settle(engine)
    impulse = np.zeros((sample_rate * 2, 2))
    impulse[0, 0] = .1
    result = engine.process(impulse)
    assert np.isfinite(result).all()
    np.testing.assert_array_equal(result[:, 1], 0)
    points = np.array([hz for hz in FREQUENCIES if hz < sample_rate * .45])
    spectrum = np.fft.rfft(result[:, 0]) / .1
    actual = 20 * np.log10(np.abs(spectrum[(points * 2).astype(int)]))
    np.testing.assert_allclose(actual, response(settings, sample_rate, points), atol=.002)
    for section in coefficients(settings, sample_rate):
        assert np.all(np.abs(np.roots(section[3:])) < 1)


@pytest.mark.parametrize("band", range(10))
def test_individual_band_center_gain_and_combined_response(band):
    values = [0.] * 10
    values[band] = 9
    settings = EqualizerSettings(True, tuple(values))
    assert response(settings, 48000, [FREQUENCIES[band]])[0] == pytest.approx(9, abs=1e-7)
    boost = EqualizerSettings(True, (12.,) * 10)
    assert max(response(boost, 48000, np.geomspace(20, 20000, 2000))) > 12


def test_smooth_preamp_bypass_coalescing_and_reset():
    engine = EqualizerProcessor()
    source = np.full((128, 2), .25)
    engine.submit(engine.prepare(EqualizerSettings(True, preamp=-24)))
    chunks = []
    for index in range(90):
        if index == 5:
            engine.submit(engine.prepare(EqualizerSettings(True, preamp=-12)))
        if index == 6:
            engine.submit(engine.prepare(EqualizerSettings(True, preamp=-6)))
        chunks.append(engine.process(source))
    result = np.concatenate(chunks)
    assert np.max(np.abs(np.diff(result[:, 0]))) < .0001
    assert result[-1, 0] == pytest.approx(.25 * 10 ** (-6 / 20))
    engine.submit(engine.prepare(EqualizerSettings(True, (12.,) * 10, 12)))
    settle(engine)
    tone = np.sin(np.arange(48000) * 2 * np.pi * 1000 / 48000)
    engine.process(np.column_stack([tone, tone]))
    assert engine.overload_blocks > 0 and engine.peak > 1
    engine.reset()
    np.testing.assert_array_equal(engine.process(np.zeros((512, 2))), 0)
    assert engine.overload_blocks == 0


def test_failure_is_nonfatal_and_new_controls_can_recover(monkeypatch):
    from mariana.equalizer import sosfilt

    engine = EqualizerProcessor()
    engine.submit(engine.prepare(EqualizerSettings(True, (1.,) * 10)))
    monkeypatch.setattr("mariana.equalizer.sosfilt", lambda *a, **kw: (_ for _ in ()).throw(ValueError("broken")))
    samples = np.ones((128, 2)) * .1
    assert engine.process(samples) is samples
    assert engine.fault
    assert engine.process(samples) is samples
    monkeypatch.setattr("mariana.equalizer.sosfilt", sosfilt)
    engine.submit(engine.prepare(EqualizerSettings()))
    settle(engine)
    assert not engine.fault
    assert engine.process(samples) is samples


def test_settings_presets_reload_and_failed_persistence(tmp_path):
    import json

    path = tmp_path / "settings.json"
    engine = EqualizerProcessor()
    service = EqualizerService(lambda: engine, persist=lambda value: path.write_text(json.dumps(value)))
    assert not service.status()["enabled"]
    service.apply({"operation": "enabled", "enabled": True})
    service.apply({"operation": "band", "frequency": 31, "gain": 4})
    service.apply({"operation": "preamp", "gain": -8})
    pending = engine.pending
    service.apply({"operation": "preset-save", "name": "Evening"})
    assert engine.pending is pending
    reloaded = EqualizerService(lambda: EqualizerProcessor(), json.loads(path.read_text()))
    assert reloaded.settings == service.settings
    assert reloaded.presets == service.presets
    with pytest.raises(ValueError, match="exists"):
        service.apply({"operation": "preset-save", "name": "evening"})
    for operation in ("preset-delete", "preset-save"):
        with pytest.raises(ValueError, match="protected"):
            service.apply({"operation": operation, "name": "Flat"})
    service.apply({"operation": "reset"})
    assert service.settings == EqualizerSettings(enabled=True)
    service.apply({"operation": "preset-apply", "name": "Evening"})
    assert service.settings.preamp == -8 and service.settings.bands[0] == 4
    service.apply({"operation": "preset-delete", "name": "Evening"})
    assert not service.presets
    previous = service.status()
    service.persist = lambda value: (_ for _ in ()).throw(OSError("disk full"))
    with pytest.raises(OSError):
        service.apply({"operation": "enabled", "enabled": False})
    assert service.status() == previous


@pytest.mark.parametrize("intent", [
    {"operation": "band", "frequency": 31, "gain": float("nan")},
    {"operation": "preamp", "gain": float("inf")},
    {"operation": "preamp", "gain": -37},
    {"operation": "band", "frequency": 32, "gain": 0},
    {"operation": "band", "frequency": 31, "gain": True},
    {"operation": "enabled", "enabled": 1},
    {"operation": "reset", "extra": "anything"},
    {"operation": "reset", "revision": -1},
    {"operation": "preset-save", "name": "../path"},
])
def test_invalid_control_never_mutates(intent):
    engine = EqualizerProcessor()
    service = EqualizerService(lambda: engine)
    previous = service.status()
    with pytest.raises(ValueError):
        service.apply(intent)
    assert service.status() == previous


def test_factory_headroom_cli_grammar_and_invalid_saved_settings():
    for preset in FACTORY_PRESETS.values():
        curve = response(replace(preset, enabled=True), 48000, np.geomspace(20, 20000, 4096))
        assert max(curve) < .001
    for token in ("1000", "1k", "1KHz", "1000hz"):
        assert frequency(token) == 1000
    assert command_intent(["band", "1k", "-2.5"]) == {"operation": "band", "frequency": 1000, "gain": -2.5}
    assert command_intent(["preset", "save", "Evening mix"])["name"] == "Evening mix"
    for invalid in (["on", "extra"], ["preamp", "nan"], ["band", "123", "2"]):
        with pytest.raises(ValueError):
            command_intent(invalid)
    engine = EqualizerProcessor(8000)
    service = EqualizerService(lambda: engine, {"enabled": True, "bands": [99] * 10})
    assert not service.settings.enabled and service.warning
    assert service.status()["available_bands"] == [True] * 7 + [False] * 3


@pytest.mark.parametrize("raw", [[], {"unexpected": 1}, {"enabled": "yes"}, {"bands": [0]},
                                 {"preamp": "3"}, {"presets": []}, {"presets": {"Flat": {}}}])
def test_malformed_persistence_is_bypassed_without_writes(raw):
    engine = EqualizerProcessor()
    writes = []
    service = EqualizerService(lambda: engine, raw, persist=writes.append)
    assert service.settings == EqualizerSettings()
    assert not writes


@pytest.mark.parametrize("rate", [0, 7999, 192001, 48000.0, True])
def test_unsupported_processing_rate_is_rejected_before_callback(rate):
    with pytest.raises(ValueError, match="sample rate"):
        EqualizerProcessor(rate)


@pytest.mark.parametrize("token", ["nan", "inf", "1e3", "1 kHz", "1.2k", "31hzextra"])
def test_frequency_grammar_is_unambiguous(token):
    with pytest.raises(ValueError):
        frequency(token)


def test_control_presets_and_capacity_boundaries():
    engine = EqualizerProcessor()
    service = EqualizerService(lambda: engine)
    for name in FACTORY_PRESETS:
        service.apply({"operation": "preset-apply", "name": name})
        assert not service.settings.enabled
    for intent in ({"operation": "preset-apply", "name": []}, {"operation": "preset-apply", "name": "missing"},
                   {"operation": "preset-delete", "name": "missing"}, {"operation": "preset-save", "name": "trailing "},
                   {"operation": "anything"}, {"operation": []}):
        with pytest.raises(ValueError):
            service.apply(intent)
    for index in range(32):
        service.apply({"operation": "preset-save", "name": f"Listening {index}"})
    with pytest.raises(ValueError, match="limit"):
        service.apply({"operation": "preset-save", "name": "One more"})
    assert len(service.presets) == 32
    saved = {"presets": {name: value.to_dict() for name, value in service.presets.items()}}
    restored = EqualizerService(lambda: engine, saved)
    assert restored.presets == service.presets
    saved["presets"]["One more"] = {}
    assert EqualizerService(lambda: engine, saved).warning


def test_runtime_missing_nonfinite_and_reset_during_transition(monkeypatch):
    from mariana.equalizer import sosfilt

    monkeypatch.setattr("mariana.equalizer.sosfilt", None)
    engine = EqualizerProcessor()
    source = np.zeros((64, 2))
    assert engine.process(source) is source and not engine.fault
    engine.submit(engine.prepare(EqualizerSettings(True, (1.,) * 10)))
    assert engine.process(source) is source and engine.fault
    monkeypatch.setattr("mariana.equalizer.sosfilt", sosfilt)
    engine.submit(engine.prepare(EqualizerSettings(True, (2.,) * 10)))
    engine.process(source)
    assert engine.next is not None
    engine.reset()
    np.testing.assert_array_equal(engine.process(source), source)
    settle(engine)
    assert engine.process(np.zeros((0, 2))).shape == (0, 2)
    assert not engine.fault
    monkeypatch.setattr("mariana.equalizer.sosfilt", lambda sections, samples, **kwargs: (np.full_like(samples, np.nan), kwargs["zi"]))
    assert engine.process(source) is source and engine.fault


@pytest.mark.parametrize(("arguments", "intent"), [
    ([], None), (["status"], None), (["preset", "list"], None),
    (["on"], {"operation": "enabled", "enabled": True}),
    (["off"], {"operation": "enabled", "enabled": False}),
    (["reset"], {"operation": "reset"}),
    (["preamp", "-12.5"], {"operation": "preamp", "gain": -12.5}),
    (["preset", "delete", "Evening"], {"operation": "preset-delete", "name": "Evening"}),
])
def test_supported_command_forms(arguments, intent):
    assert command_intent(arguments) == intent


@pytest.mark.parametrize("error", [ImportError, OSError, RuntimeError, ValueError])
def test_backend_initialization_failure_preserves_dry_playback(monkeypatch, error):
    import builtins

    from mariana import equalizer

    original_import = builtins.__import__
    imports = []

    def unavailable(name, *args, **kwargs):
        if name == "scipy.signal":
            imports.append(name)
            raise error("Unavailable processing backend")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(equalizer, "sosfilt", equalizer._lazy_sosfilt)
    monkeypatch.setattr(builtins, "__import__", unavailable)
    engine = EqualizerProcessor()
    samples = np.full((512, 2), .125)
    assert engine.process(samples) is samples
    assert imports == []
    engine.submit(engine.prepare(EqualizerSettings(True, (3.,) * 10)))
    assert imports == ["scipy.signal"]
    assert engine.process(samples) is samples
    assert engine.fault
    assert imports == ["scipy.signal"]  # The callback must not retry imports.
    engine.submit(engine.prepare(EqualizerSettings()))
    settle(engine)
    assert engine.process(samples) is samples
    assert not engine.fault

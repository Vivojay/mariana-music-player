"""Local-listening graphic EQ: prepared controls, bounded stereo DSP, and settings."""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np


def _lazy_sosfilt(*args: Any, **kwargs: Any) -> Any:
    """Placeholder replaced before a non-flat bank reaches the audio callback."""
    backend = _load_sosfilt()
    if backend is None:
        raise RuntimeError("Equalizer filter backend is unavailable")
    return backend(*args, **kwargs)


sosfilt: Callable[..., Any] | None = _lazy_sosfilt
_SOSFILT_LOCK = threading.Lock()


def _load_sosfilt() -> Callable[..., Any] | None:
    """Load the optional DSP backend on a control thread, only when needed."""
    global sosfilt
    if sosfilt is not _lazy_sosfilt:
        return sosfilt
    with _SOSFILT_LOCK:
        if sosfilt is not _lazy_sosfilt:
            return sosfilt
        try:
            from scipy.signal import sosfilt as scipy_sosfilt
        except Exception:
            # Optional backend initialization must not prevent dry playback.
            sosfilt = None
        else:
            sosfilt = scipy_sosfilt
    return sosfilt

FREQUENCIES = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
Q = math.sqrt(2.0)  # Approximately one octave at low frequencies; constant-Q peaks.
TRANSITION_SECONDS = 0.1
MAX_PRESETS = 32


def gain(value: object, minimum: float = -12.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Gain must be a finite number")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= 12:
        raise ValueError(f"Gain must be between {minimum:g} and 12 dB")
    return number


def frequency(value: str) -> int:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(k(?:hz)?|hz)?", value.casefold())
    if not match:
        raise ValueError("Use a band frequency such as 31, 1000, 1k, or 1kHz")
    number = float(match[1]) * (1000 if (match[2] or "").startswith("k") else 1)
    if number not in FREQUENCIES:
        raise ValueError("Frequency must identify one of the ten EQ bands")
    return int(number)


@dataclass(frozen=True)
class EqualizerSettings:
    enabled: bool = False
    bands: tuple[float, ...] = (0.0,) * 10
    preamp: float = 0.0

    @classmethod
    def parse(cls, raw: object) -> EqualizerSettings:
        if not isinstance(raw, Mapping) or set(raw) - {"enabled", "bands", "preamp", "presets"}:
            raise ValueError("Invalid equalizer settings")
        enabled, bands = raw.get("enabled", False), raw.get("bands", [0.0] * 10)
        if type(enabled) is not bool or not isinstance(bands, (list, tuple)) or len(bands) != 10:
            raise ValueError("Equalizer requires an enabled flag and ten band gains")
        return cls(enabled, tuple(gain(value) for value in bands), gain(raw.get("preamp", 0), -36))

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "bands": list(self.bands), "preamp": self.preamp}


FACTORY_PRESETS = {
    "Flat": EqualizerSettings(),
    "Bass Boost": EqualizerSettings(bands=(4, 3, 2, 0, 0, 0, 0, 0, 0, 0), preamp=-10),
    "Treble Boost": EqualizerSettings(bands=(0, 0, 0, 0, 0, 0, 1, 2, 3, 2), preamp=-9),
    "Vocal Clarity": EqualizerSettings(bands=(-2, -2, -1, 0, 1, 2, 2, 1, 0, -1), preamp=-7),
}


def coefficients(settings: EqualizerSettings, sample_rate: int) -> np.ndarray:
    """RBJ peaking filters, normalized a0; never called by the audio callback."""
    if type(sample_rate) is not int or not 8000 <= sample_rate <= 192000:
        raise ValueError("Unsupported EQ processing sample rate")
    sections = []
    for center, db in zip(FREQUENCIES, settings.bands, strict=True):
        if center >= sample_rate * 0.45 or db == 0 or not settings.enabled:
            sections.append([1., 0., 0., 1., 0., 0.])
            continue
        omega = 2 * math.pi * center / sample_rate
        amplitude, alpha = 10 ** (db / 40), math.sin(omega) / (2 * Q)
        cosine = math.cos(omega)
        a0 = 1 + alpha / amplitude
        sections.append([(1 + alpha * amplitude) / a0, -2 * cosine / a0,
                         (1 - alpha * amplitude) / a0, 1., -2 * cosine / a0,
                         (1 - alpha / amplitude) / a0])
    return np.asarray(sections, dtype=np.float64)


def response(settings: EqualizerSettings, sample_rate: int, points: Sequence[float] | np.ndarray) -> np.ndarray:
    sections = coefficients(settings, sample_rate)
    z = np.exp(-2j * np.pi * np.asarray(points) / sample_rate)
    magnitude = np.ones(len(points))
    for b0, b1, b2, _, a1, a2 in sections:
        magnitude *= np.abs((b0 + b1 * z + b2 * z * z) / (1 + a1 * z + a2 * z * z))
    return 20 * np.log10(np.maximum(magnitude, 1e-30)) + (settings.preamp if settings.enabled else 0)


@dataclass
class _Bank:
    sections: np.ndarray
    state: np.ndarray
    preamp: float
    flat: bool

    def run(self, samples: np.ndarray) -> np.ndarray:
        if self.flat:
            return samples
        assert callable(sosfilt)
        result, self.state = sosfilt(self.sections, samples, axis=0, zi=self.state)
        return result * self.preamp


class EqualizerProcessor:
    """One consumer (audio callback), latest prepared bank mailbox, no control locks.

    Filter design and delay/ramp allocation happen on the control thread. Processing
    uses at most two ten-section banks. New changes wait for a 100 ms ramp to finish;
    intermediate pending values coalesce, but the newest bank is never discarded.
    """

    def __init__(self, sample_rate: int = 48000) -> None:
        coefficients(EqualizerSettings(), sample_rate)
        self.sample_rate = sample_rate
        self.ramp = np.linspace(0, 1, round(sample_rate * TRANSITION_SECONDS))[:, None]
        self.current = self.prepare(EqualizerSettings())
        self.pending: _Bank | None = None
        self.next: _Bank | None = None
        self.rejected: _Bank | None = None
        self.offset = 0
        self.reset_serial = 0
        self.seen_reset = 0
        self.peak = 0.0
        self.overload_blocks = 0
        self.fault = False

    def prepare(self, settings: EqualizerSettings) -> _Bank:
        flat = not settings.enabled or (not any(settings.bands) and settings.preamp == 0)
        if not flat:
            _load_sosfilt()
        return _Bank(coefficients(settings, self.sample_rate), np.zeros((10, 2, 2)),
                     10 ** (settings.preamp / 20) if settings.enabled else 1., flat)

    def submit(self, bank: _Bank) -> None:
        self.pending = bank

    def reset(self) -> None:
        # Delay memories are callback-owned; a seek/stop only publishes a reset token.
        self.reset_serial += 1

    def process(self, samples: np.ndarray) -> np.ndarray:
        if not len(samples):
            return samples
        if self.seen_reset != self.reset_serial:
            self.current.state.fill(0)
            if self.next is not None:
                self.next.state.fill(0)
            self.seen_reset = self.reset_serial
            self.peak = 0
            self.overload_blocks = 0
        if self.fault:
            if self.pending is None or self.pending is self.rejected:
                return samples
            self.current.state.fill(0)
        if self.next is None and self.pending is not None and self.pending is not self.current:
            # Do not clear a newer writer's mailbox value after taking its reference.
            self.next = self.pending
            self.offset = 0
            self.fault = not self.next.flat and not callable(sosfilt)
        if self.fault:
            self.rejected = self.next
            self.next = None
            return samples
        try:
            result = self.current.run(samples)
            if self.next is not None:
                target = self.next.run(samples)
                count = min(len(samples), len(self.ramp) - self.offset)
                mixed = target.copy()
                weight = self.ramp[self.offset:self.offset + count]
                mixed[:count] = result[:count] * (1 - weight) + target[:count] * weight
                result = mixed
                self.offset += count
                if self.offset == len(self.ramp):
                    self.current = self.next
                    self.next = None
            if not np.isfinite(result).all():
                raise FloatingPointError("Non-finite EQ output")
            self.peak = float(np.max(np.abs(result)))
            if self.peak > 1:
                self.overload_blocks += 1
            return result
        except Exception:
            self.fault = True
            self.rejected = self.next or self.current
            self.next = None
            return samples


class EqualizerService:
    """Serialized settings transactions; desktop and CLI share the same authority."""

    def __init__(self, engine: Callable[[], EqualizerProcessor], raw: object = None,
                 persist: Callable[[dict[str, Any]], None] = lambda _value: None) -> None:
        self.engine = engine
        self.persist = persist
        self.lock = threading.RLock()
        self.revision = 0
        self.presets: dict[str, EqualizerSettings] = {}
        self.warning: str | None = None
        try:
            self.settings = EqualizerSettings.parse(raw or {})
            raw_presets = raw.get("presets", {}) if isinstance(raw, Mapping) else {}
            if not isinstance(raw_presets, Mapping) or len(raw_presets) > MAX_PRESETS:
                raise ValueError("Invalid presets")
            for name, preset in raw_presets.items():
                self.presets[self._name(name)] = EqualizerSettings.parse(preset)
        except ValueError:
            self.settings = EqualizerSettings()
            self.presets = {}
            self.warning = "Invalid saved EQ settings; playback is bypassed. Saved data was not overwritten."
        self.engine().submit(self.engine().prepare(self.settings))

    @staticmethod
    def _name(name: object) -> str:
        if not isinstance(name, str) or not re.fullmatch(r"[\w][\w .()-]{0,47}", name):
            raise ValueError("Preset names must contain 1-48 letters, numbers, spaces, dots, parentheses or hyphens")
        if name != name.strip() or name.casefold() in {key.casefold() for key in FACTORY_PRESETS}:
            raise ValueError("Factory preset names are protected")
        return name

    def status(self) -> dict[str, Any]:
        with self.lock:
            engine = self.engine()
            points = np.geomspace(20, min(20000, engine.sample_rate * .45), 128)
            curve = response(self.settings, engine.sample_rate, points)
            return {**self.settings.to_dict(), "revision": self.revision, "sample_rate": engine.sample_rate,
                    "frequencies": list(FREQUENCIES),
                    "available_bands": [value < engine.sample_rate * .45 for value in FREQUENCIES],
                    "response": [[float(hz), float(db)] for hz, db in zip(points, curve, strict=True)],
                    "recommended_preamp": -min(36, sum(max(0, value) for value in self.settings.bands)),
                    "peak": engine.peak, "overload_blocks": engine.overload_blocks,
                    "fault": engine.fault, "warning": self.warning,
                    "presets": [{"name": name, "factory": True} for name in FACTORY_PRESETS]
                    + [{"name": name, "factory": False} for name in sorted(self.presets)]}

    def apply(self, intent: Mapping[str, Any]) -> dict[str, Any]:
        with self.lock:
            revision = intent.get("revision", self.revision)
            if type(revision) is not int or revision != self.revision:
                raise ValueError("Equalizer changed; refresh and try again")
            operation = intent.get("operation")
            required = {"enabled": {"enabled"}, "band": {"frequency", "gain"}, "preamp": {"gain"},
                        "reset": set(), "preset-apply": {"name"}, "preset-save": {"name"},
                        "preset-delete": {"name"}}
            if not isinstance(operation, str) or operation not in required or set(intent) - {"revision", "operation"} != required[operation]:
                raise ValueError("Invalid equalizer control")
            settings, presets = self.settings, dict(self.presets)
            if operation == "enabled":
                if type(intent["enabled"]) is not bool:
                    raise ValueError("Enabled must be true or false")
                settings = replace(settings, enabled=intent["enabled"])
            elif operation == "band":
                hz = intent["frequency"]
                if type(hz) is not int or hz not in FREQUENCIES:
                    raise ValueError("Unknown equalizer band")
                bands = list(settings.bands)
                bands[FREQUENCIES.index(hz)] = gain(intent["gain"])
                settings = replace(settings, bands=tuple(bands))
            elif operation == "preamp":
                settings = replace(settings, preamp=gain(intent["gain"], -36))
            elif operation == "reset":
                settings = EqualizerSettings(enabled=settings.enabled)
            elif operation == "preset-apply":
                name = intent["name"]
                if not isinstance(name, str) or name not in FACTORY_PRESETS | presets:
                    raise ValueError("Unknown equalizer preset")
                settings = replace((FACTORY_PRESETS | presets)[name], enabled=settings.enabled)
            else:
                name = self._name(intent["name"])
                if operation == "preset-save":
                    if len(presets) >= MAX_PRESETS or name.casefold() in {key.casefold() for key in presets}:
                        raise ValueError("Preset exists or the 32-preset limit was reached; choose another name")
                    presets[name] = settings
                elif name not in presets:
                    raise ValueError("Unknown user preset")
                else:
                    del presets[name]
            bank = self.engine().prepare(settings) if settings != self.settings else None
            self.persist({**settings.to_dict(), "presets": {name: value.to_dict() for name, value in presets.items()}})
            self.settings, self.presets = settings, presets
            self.revision += 1
            self.warning = None
            if bank is not None:
                self.engine().submit(bank)
            return self.status()


def command_intent(arguments: list[str]) -> dict[str, Any] | None:
    if not arguments or arguments in (["status"], ["preset", "list"]):
        return None
    if arguments in (["on"], ["off"]):
        return {"operation": "enabled", "enabled": arguments[0] == "on"}
    if arguments == ["reset"]:
        return {"operation": "reset"}
    if len(arguments) == 3 and arguments[0] == "band":
        return {"operation": "band", "frequency": frequency(arguments[1]), "gain": gain(float(arguments[2]))}
    if len(arguments) == 2 and arguments[0] == "preamp":
        return {"operation": "preamp", "gain": gain(float(arguments[1]), -36)}
    if len(arguments) == 3 and arguments[0] == "preset" and arguments[1] in {"apply", "save", "delete"}:
        return {"operation": f"preset-{arguments[1]}", "name": arguments[2]}
    raise ValueError('Use eq status/on/off/band/preamp/reset or eq preset list/apply/save/delete "name"')

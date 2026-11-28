"""Session-local stereo monitor effects. One callback owns each processor."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from itertools import pairwise

import numpy as np

# Levels are wet percentages; pitch is measured in semitones.
LIMITS: dict[str, tuple[float, float]] = dict.fromkeys(("chorus", "delay", "room", "drive", "tremolo", "robot", "deess", "tune", "vocoder", "tapestop", "bitcrush"), (0.0, 100.0))
LIMITS["pitch"] = (-12., 12.)


@dataclass(frozen=True)
class Rack:
    chorus: float = 0
    delay: float = 0
    room: float = 0
    drive: float = 0
    tremolo: float = 0
    robot: float = 0
    deess: float = 0
    pitch: float = 0
    tune: float = 0
    vocoder: float = 0
    tapestop: float = 0
    bitcrush: float = 0


PRESETS = {
    "dry": Rack(),
    "vocal-booth": Rack(deess=65, room=13),
    "choir": Rack(chorus=62, room=33),
    "cassette": Rack(drive=38, chorus=15),
    "bit-sampler": Rack(bitcrush=75),
    "cavern": Rack(room=85, delay=28),
    "robot": Rack(robot=75, drive=10),
    "subvoice": Rack(pitch=-5, room=12),
    "bright-voice": Rack(pitch=3, chorus=20),
    "chromatic": Rack(tune=100, room=10),
    "synth-voice": Rack(vocoder=95, chorus=15),
}


def setting(rack: Rack, key: str, text: str) -> Rack:
    if key not in LIMITS:
        raise ValueError("Choose an FX control: " + ", ".join(LIMITS))
    lo, hi = LIMITS[key]
    try:
        value = float(text)
    except (TypeError, ValueError):
        value = math.nan
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{key} accepts values from {lo:g} to {hi:g}")
    return replace(rack, **{key: value})


def _voice_pitch(samples: np.ndarray, rate: float) -> float | None:
    # Normalized autocorrelation on a 12 kHz mono analysis signal. Reject noisy
    # and unvoiced frames; use the first strong local maximum to avoid octaves.
    x = samples - np.mean(samples)
    power = float(np.dot(x, x))
    if power / len(x) < .00004:
        return None
    first, last = round(rate / 900), min(len(x) // 2, math.ceil(rate / 70))
    spectrum = np.fft.rfft(x, n=2 * len(x))
    corr = np.fft.irfft(spectrum * spectrum.conj())[:last + 2]
    cumulative = np.r_[0., np.cumsum(x * x)]
    lag = np.arange(len(corr))
    weights = np.sqrt(np.maximum(1e-12, cumulative[len(x) - lag] * (power - cumulative[lag])))
    score = corr / weights
    peaks = np.where((score[first:last+1] >= score[first-1:last]) &
                     (score[first:last+1] > score[first+1:last+2]))[0] + first
    peaks = peaks[score[peaks] >= max(.82, .94 * max(score[first:last+1]))]
    if not len(peaks):
        return None
    i = peaks[0]
    a, b, c = score[i-1:i+2]
    denominator = 2 * (2*b-a-c)
    delta = (c-a) / denominator if denominator > 1e-9 else 0
    return rate / (i + np.clip(delta, -.5, .5))


class FilterVocoder:
    """Eight modulator band envelopes drive matching synthetic carrier bands."""
    def __init__(self, rate):
        try:
            from scipy.signal import butter, lfilter, sosfilt
        except ImportError as exc:
            raise ValueError("The vocoder requires SciPy in this Python environment.") from exc
        self.rate = rate
        self.filter = sosfilt
        self.smooth = lfilter
        self.alpha = math.exp(-1 / (.009 * rate))
        edges = np.geomspace(110, min(8000, .42 * rate), 9)
        self.bands = [np.asarray(butter(2, (lo, hi), btype="bandpass", fs=rate, output="sos"))
                      for lo, hi in pairwise(edges)]
        self.states = [np.zeros((len(sos), 2, 2)) for sos in self.bands]
        self.energy = np.zeros((len(self.bands), 1))

    def process(self, block, stamp):
        carrier = 2 * np.mod(stamp * (110 / self.rate), 1.) - 1
        modulator = np.mean(block, axis=1)
        pair = np.column_stack((modulator, carrier))
        result = np.zeros(len(block))
        for i, sos in enumerate(self.bands):
            band, self.states[i] = self.filter(sos, pair, axis=0, zi=self.states[i])
            envelope, self.energy[i] = self.smooth([1-self.alpha], [1, -self.alpha],
                                                    np.abs(band[:, 0]), zi=self.energy[i])
            result += envelope * band[:, 1] * 5
        return result[:, None]


class EffectProcessor:
    """Process fixed-length blocks; parameter changes are prepared off the callback."""
    def __init__(self, rack: Rack, rate: int = 48000):
        self.rack = rack
        self.rate = rate
        self.position = 0
        self.phase = 0.
        self.pitch_adjust = 0.
        self.buffer = np.zeros((math.ceil(rate * .8) + 4096, 2), np.float32)
        self.next_analysis = 0
        self.crush_sample = np.zeros(2, dtype=np.float32)
        self.vocoder = FilterVocoder(rate) if rack.vocoder else None
        self.deesser = None
        if rack.deess:
            from .deesser import VoiceDeEsser
            self.deesser = VoiceDeEsser("strong", rate)
        self.fault = False

    def render(self, block, session):
        if getattr(self, "_session", None) != session:
            self._session = session
            self.position = self.next_analysis = 0
            self.phase = self.pitch_adjust = 0.
            self.buffer.fill(0)
            self.crush_sample.fill(0)
            if self.deesser:
                self.deesser.process(block[:0], None)
            if self.vocoder:
                self.vocoder.energy.fill(0)
                for state in self.vocoder.states:
                    state.fill(0)
        return self.process(block)

    def process(self, block):
        if self.fault or not len(block):
            return block
        try:
            result = (self._block(block) if len(block) <= 2048 else
                      np.concatenate([self._block(block[i:i+2048]) for i in range(0, len(block), 2048)]))
            if not np.isfinite(result).all():
                raise ValueError("Non-finite effect output")
            return np.clip(result, -1., 1.).astype(np.float32, copy=False)
        except Exception:
            self.fault = True
            return block

    def _block(self, block):
        rack = self.rack
        scale = self.rate
        stamp = self.position + np.arange(len(block))
        self.position += len(block)
        size = len(self.buffer)
        x = block
        if self.deesser is not None:
            wet = rack.deess / 100
            x = (1-wet) * x + wet * self.deesser.process(x, 1)
        if self.vocoder is not None:
            wet = rack.vocoder / 100
            x = (1-wet) * x + wet * self.vocoder.process(x, stamp)
        self.buffer[stamp % size] = x

        def tap(seconds):
            index = stamp - seconds * scale
            lo = np.floor(index).astype(np.int64)
            frac = (index-lo)[:, None]
            return self.buffer[lo % size] * (1-frac) + self.buffer[(lo+1) % size] * frac

        if rack.tune and self.position >= self.next_analysis:
            step = max(1, round(scale / 12000))
            history = self.buffer[(self.position + np.arange(-768*step, 0, step)) % size].mean(axis=1)
            frequency = _voice_pitch(history, scale / step)
            self.pitch_adjust = 0.
            if frequency:
                note = 69 + 12 * math.log2(frequency / 440.)
                self.pitch_adjust = (round(note)-note) * rack.tune / 100
            self.next_analysis = self.position + round(scale * .02)
        if rack.pitch or rack.tune:
            # Two overlapping fractional delay lines move at the desired pitch
            # ratio. Smooth gain crossovers mask each grain's discontinuity.
            drift = (1 - 2 ** ((rack.pitch + self.pitch_adjust) / 12)) / (.045 * scale)
            phase = (self.phase + drift * np.arange(len(x))) % 1
            self.phase = (self.phase + drift * len(x)) % 1
            weight = np.sin(np.pi * phase)[:, None] ** 2
            x = weight * tap(.002 + .045 * phase) + (1-weight) * tap(.002 + .045 * ((phase+.5) % 1))
        if rack.chorus:
            left = tap(.019 + .004*np.sin(stamp * 2*np.pi*.72 / scale))
            right = tap(.023 + .005*np.sin(stamp * 2*np.pi*.87 / scale))
            wet = rack.chorus / 155
            x = (1-wet)*x + wet*np.column_stack((left[:, 0], right[:, 1]))
        if rack.delay:
            x = x + rack.delay / 100 * (.5*tap(.225) + .28*tap(.450) + .14*tap(.675))
        if rack.room:
            reflections = (.34*tap(.031) + .25*tap(.051)[:, ::-1] + .20*tap(.079)
                           + .15*tap(.109)[:, ::-1] + .10*tap(.167) + .075*tap(.251)[:, ::-1])
            x = x + rack.room / 100 * reflections
        if rack.robot:
            mix = rack.robot / 100
            x = x * ((1-mix) + mix * np.sin(stamp*2*np.pi*37/scale))[:, None]
        if rack.tremolo:
            x = x * (1 - rack.tremolo/200 * (1-np.cos(stamp*2*np.pi*5/scale)))[:, None]
        if rack.tapestop:
            duration = .10 + .90 * rack.tapestop / 100
            elapsed = np.minimum(stamp / scale, duration)
            x = tap(.5 * elapsed**2 / duration) * (1-elapsed/duration)[:, None]
        if rack.drive:
            gain = 1 + rack.drive*.055
            x = np.tanh(x * gain) / math.tanh(gain)
        if rack.bitcrush:
            amount = rack.bitcrush / 100
            hold = 1 + math.floor(15 * amount + .5)
            levels = 2 ** (15 - math.floor(12 * amount + .5))
            capture = stamp - stamp % hold - stamp[0]
            quantized = np.floor(x[np.maximum(0, capture)] * levels + .5) / levels
            quantized[capture < 0] = self.crush_sample
            self.crush_sample[:] = quantized[-1]
            x = (1 - amount) * x + amount * quantized
        return x

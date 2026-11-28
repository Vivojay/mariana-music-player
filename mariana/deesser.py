"""Stereo-linked, frequency-sensitive voice compression for local listening."""
from __future__ import annotations

import math

import numpy as np

# Maximum broadband reduction, in dB, when the sibilance detector is saturated.
MODES = {"off": 0, "gentle": 3, "balanced": 6, "strong": 9}


def validate_mode(value: object) -> str:
    if not isinstance(value, str) or value not in MODES:
        raise ValueError("Choose off, gentle, balanced or strong for spoken-word de-essing")
    return value


class VoiceDeEsser:
    """One callback owns filter memories. Prepare a replacement on the control thread."""

    def __init__(self, mode: str, rate: int) -> None:
        self.mode = validate_mode(mode)
        try:
            from scipy.signal import butter, lfilter, sosfilt
        except ImportError as exc:
            raise ValueError("Spoken-word processing requires SciPy") from exc
        self._lfilter = lfilter
        self._sosfilt = sosfilt
        upper = min(11000, 0.45 * rate)
        if upper <= 4500:
            raise ValueError("Spoken-word processing needs an output rate above 10 kHz")
        self._band = np.asarray(butter(2, [4500, upper], btype="bandpass", fs=rate, output="sos"))
        self._band_state = np.zeros((len(self._band), 2, 2))
        self._energy_state = np.zeros((1, 2))
        self._gain_state = np.zeros(1)
        self._energy_pole = math.exp(-1 / (rate * 0.003))
        self._gain_pole = math.exp(-1 / (rate * 0.006))
        self._stream: int | None = None

    def process(self, block: np.ndarray, stream: int | None) -> np.ndarray:
        if self._stream != stream:
            self._band_state.fill(0)
            self._energy_state.fill(0)
            self._gain_state.fill(0)
            self._stream = stream
        if stream is None or not len(block):
            return block

        # Link channels to preserve stereo placement. Both absolute sibilant power
        # and its fraction of the total must be significant to trigger reduction.
        band, self._band_state = self._sosfilt(self._band, block, axis=0, zi=self._band_state)
        power = np.column_stack((np.mean(band * band, axis=1), np.mean(block * block, axis=1)))
        p = self._energy_pole
        energies, self._energy_state = self._lfilter([1 - p], [1, -p], power, axis=0, zi=self._energy_state)
        high, total = energies.T
        threshold = 10 ** (-38 / 10)
        activity = np.clip((high / np.maximum(total, 1e-12) - 0.12) / 0.46, 0, 1)
        above = np.clip(10 * np.log10(np.maximum(high, threshold) / threshold) / 15, 0, 1)
        reduction_db = MODES[self.mode] * activity * above
        p = self._gain_pole
        smooth_db, self._gain_state = self._lfilter([1 - p], [1, -p], reduction_db, zi=self._gain_state)
        return (block * (10 ** (-smooth_db / 20))[:, None]).astype(block.dtype, copy=False)

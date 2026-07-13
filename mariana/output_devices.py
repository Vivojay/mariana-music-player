"""Discover the operating-system default audio output without stale PortAudio labels."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import sounddevice


class OutputDeviceError(RuntimeError):
    """Raised when no usable output device can be resolved."""


@dataclass(frozen=True, slots=True)
class OutputDeviceInfo:
    """An OS endpoint paired with the PortAudio route used to open it."""

    key: str
    name: str
    index: int | str | None
    portaudio_name: str
    hostapi: str
    endpoint_id: str | None = None

    @property
    def route(self) -> str:
        return self.hostapi or "system default"


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _device_score(endpoint_name: str, candidate_name: str, hostapi: str) -> float:
    endpoint = _normalized(endpoint_name)
    candidate = _normalized(candidate_name)
    if not endpoint or not candidate:
        return 0.0
    score = SequenceMatcher(None, endpoint, candidate).ratio() * 50
    if endpoint == candidate:
        score += 80
    elif endpoint in candidate or candidate in endpoint:
        score += 45
    generic = {"audio", "device", "headphones", "headset", "output", "speakers", "stereo"}
    endpoint_tokens = set(endpoint.split()) - generic
    candidate_tokens = set(candidate.split()) - generic
    if endpoint_tokens:
        score += 50 * len(endpoint_tokens & candidate_tokens) / len(endpoint_tokens)
    if "wasapi" in hostapi.casefold():
        score += 25
    elif "directsound" in hostapi.casefold():
        score += 10
    return score


def _windows_default_endpoint() -> tuple[str, str] | None:
    if os.name != "nt":
        return None
    try:
        from comtypes import CoInitialize, CoUninitialize
        from pycaw.pycaw import AudioUtilities

        CoInitialize()
        try:
            endpoint = AudioUtilities.GetSpeakers()
            name = str(getattr(endpoint, "FriendlyName", "") or "").strip()
            endpoint_id = str(getattr(endpoint, "id", "") or "").strip()
            if name and endpoint_id:
                return endpoint_id, name
        finally:
            CoUninitialize()
    except Exception:
        # PortAudio remains a valid cross-platform fallback when Core Audio is
        # temporarily unavailable (including during Windows logon/device churn).
        return None
    return None


def _hostapi_name(audio: Any, index: int) -> str:
    try:
        return str(audio.query_hostapis(index).get("name") or "")
    except Exception:
        return ""


def _enumerate_outputs(audio: Any) -> list[tuple[int, dict[str, Any], str]]:
    try:
        queried = audio.query_devices()
        devices = [queried] if isinstance(queried, Mapping) else list(queried)
    except Exception as error:
        raise OutputDeviceError(f"Audio output enumeration failed: {error}") from error
    result = []
    for index, raw in enumerate(devices):
        device = dict(raw)
        if int(device.get("max_output_channels", 1) or 0) <= 0:
            continue
        result.append((index, device, _hostapi_name(audio, int(device.get("hostapi") or 0))))
    if not result:
        raise OutputDeviceError("No enabled audio output device is available")
    return result


def _system_mapper(outputs: list[tuple[int, dict[str, Any], str]]) -> tuple[int, dict[str, Any], str] | None:
    preferred = ("microsoft sound mapper - output", "primary sound driver")
    for target in preferred:
        for candidate in outputs:
            if _normalized(str(candidate[1].get("name") or "")) == _normalized(target):
                return candidate
    return None


def default_output_device(audio: Any = sounddevice) -> OutputDeviceInfo:
    """Return the current OS default and the best route for a new stream.

    On Windows, Core Audio supplies the authoritative endpoint identity and
    friendly name. PortAudio is used only to choose a route. The Windows
    system mapper is retained as a fallback for a Bluetooth endpoint connected
    after PortAudio initialized, because it resolves the current default when
    the stream is opened.
    """

    outputs = _enumerate_outputs(audio)
    windows_endpoint = _windows_default_endpoint()
    if windows_endpoint:
        endpoint_id, endpoint_name = windows_endpoint
        ranked = sorted(
            outputs,
            key=lambda item: _device_score(endpoint_name, str(item[1].get("name") or ""), item[2]),
            reverse=True,
        )
        best = ranked[0]
        if _device_score(endpoint_name, str(best[1].get("name") or ""), best[2]) < 55:
            best = _system_mapper(outputs) or best
        index, device, hostapi = best
        return OutputDeviceInfo(
            key=endpoint_id.casefold(),
            name=endpoint_name,
            index=index,
            portaudio_name=str(device.get("name") or endpoint_name),
            hostapi=hostapi,
            endpoint_id=endpoint_id,
        )

    try:
        default = dict(audio.query_devices(kind="output"))
    except Exception as error:
        raise OutputDeviceError(f"The system default audio output is unavailable: {error}") from error
    index_value = default.get("index")
    index = int(str(index_value)) if index_value is not None else None
    hostapi = _hostapi_name(audio, int(default.get("hostapi") or 0))
    name = str(default.get("name") or "System default output")
    key = f"{hostapi}:{index}:{name}".casefold()
    return OutputDeviceInfo(key, name, index, name, hostapi)

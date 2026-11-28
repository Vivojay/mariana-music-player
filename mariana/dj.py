"""Two local decks sharing one stereo output clock and post-fader recorder."""

from __future__ import annotations

import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .toolchain import find_tool_executable

SAMPLE_RATE = 48000
MAX_TRACK_SECONDS = 2 * 60 * 60
HELP = """DJ studio · A and B share a stereo master
dj load A|B FILE|current|LIBRARY_INDEX
dj play|pause|stop A|B|all       dj seek A|B SECONDS
dj cue A|B set|go 1..8           dj loop A|B START END|off
dj gain A|B 0..200               dj rate A|B 0.25..4
dj crossfade 0..100 [SECONDS]    (0 = A, 100 = B)
dj record start [FILE.wav]       dj record stop
dj export [COPY.wav]             dj share
dj status                        dj close
dj mixxx                         (open an installed Mixxx)"""


def number(value, minimum, maximum, label):
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = math.nan
    if not minimum <= result <= maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return result


@dataclass
class Deck:
    source: Path
    storage: tempfile.TemporaryDirectory
    samples: np.memmap
    position: float = 0.0
    gain: float = 1.0
    rate: float = 1.0
    playing: bool = False
    cues: dict[int, float] = field(default_factory=dict)
    loop: tuple[int, int] | None = None

    @classmethod
    def load(cls, path, configured_ffmpeg):
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"Local audio file missing: {path}")
        ffmpeg = find_tool_executable("ffmpeg", configured_ffmpeg)
        if not ffmpeg:
            raise ValueError("DJ decks need FFmpeg. Run 'tools setup' in Mariana or add ffmpeg to PATH.")
        storage = tempfile.TemporaryDirectory(prefix="mariana-dj-")
        raw = Path(storage.name, "deck.f32")
        try:
            subprocess.run([
                ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:a:0",
                "-t", str(MAX_TRACK_SECONDS + 1), "-ac", "2", "-ar", str(SAMPLE_RATE),
                "-c:a", "pcm_f32le", "-f", "f32le", str(raw),
            ], check=True, timeout=300, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            size = raw.stat().st_size
            frames = size // 8
            if not frames or size % 8 or frames > MAX_TRACK_SECONDS * SAMPLE_RATE:
                raise ValueError("Choose a decodable audio file between one sample and two hours long.")
            samples = np.memmap(raw, dtype="<f4", mode="r", shape=(frames, 2))
            return cls(path, storage, samples)
        except BaseException as error:
            storage.cleanup()
            if isinstance(error, (OSError, subprocess.SubprocessError)):
                raise ValueError(f"Could not decode {path.name}. Check the audio, free disk space and FFmpeg.") from error
            raise

    def close(self):
        try:
            mapping = getattr(self.samples, "_mmap", None)
            if mapping is not None:
                mapping.close()
        finally:
            self.storage.cleanup()

    def seek(self, frame):
        if self.loop and not self.loop[0] <= frame < self.loop[1]:
            self.loop = None
        self.position = frame

    def render(self, frames):
        output = np.zeros((frames, 2), dtype=np.float32)
        if not self.playing:
            return output
        positions = self.position + self.rate * np.arange(frames)
        advance = self.position + self.rate * frames
        if self.loop:
            first, end = self.loop
            beyond = positions >= end
            positions[beyond] = first + (positions[beyond] - first) % (end - first)
            if advance >= end:
                advance = first + (advance - first) % (end - first)
        valid = positions < len(self.samples)
        positions = positions[valid]
        left = positions.astype(np.int64)
        right = np.minimum(left + 1, len(self.samples) - 1)
        if self.loop:
            right[left == self.loop[1] - 1] = self.loop[0]
        fraction = (positions - left).astype(np.float32)[:, None]
        output[valid] = (self.samples[left] * (1.0 - fraction) + self.samples[right] * fraction) * self.gain
        self.position = min(advance, len(self.samples))
        if self.position >= len(self.samples):
            self.playing = False
        return output


class MasterRecording:
    """A bounded handoff keeps WAV encoding and file writes off the output callback."""

    def __init__(self, path):
        self.path = path
        raw = path.open("xb")
        try:
            # The writer thread owns and closes both handles.
            self.wav = wave.open(raw, "wb")  # noqa: SIM115
            self.wav.setparams((2, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
            self.blocks = queue.Queue(maxsize=256)
            self.error = None
            self.thread = threading.Thread(target=self._write, args=(raw,), daemon=True, name="dj-recorder")
            self.thread.start()
        except BaseException:
            raw.close()
            path.unlink(missing_ok=True)
            raise

    def append(self, block):
        if not self.error:
            try:
                self.blocks.put_nowait(block)
            except queue.Full:
                self.error = "Recording storage could not keep up with playback."

    def _write(self, raw):
        try:
            with raw, self.wav as output:
                total = 0
                while (block := self.blocks.get()) is not None:
                    total += len(block) * 4
                    if total > 0xFFFFFFFF - 36:
                        raise ValueError("This recording exceeded the WAV size limit.")
                    output.writeframesraw(np.rint(block * 32767).astype("<i2").tobytes())
        except Exception as error:
            self.error = str(error)

    def finish(self):
        while self.thread.is_alive():
            try:
                self.blocks.put(None, timeout=0.1)
                break
            except queue.Full:
                continue
        self.thread.join()
        if self.error:
            raise ValueError(f"Recording interrupted: {self.error} The partial capture is at {self.path}")
        return self.path


def default_output(callback):
    try:
        import sounddevice
        return sounddevice.OutputStream(samplerate=SAMPLE_RATE, channels=2, dtype="float32",
                                        blocksize=1024, callback=callback)
    except (ImportError, OSError) as error:
        raise ValueError("Install Mariana's sounddevice dependency and PortAudio for stereo output.") from error


def wav_path(text):
    path = Path(text).expanduser().resolve()
    if path.suffix.lower() != ".wav":
        raise ValueError("Choose an output filename ending in .wav.")
    return path


def launch_mixxx(sources):
    candidates = [shutil.which("mixxx")]
    if sys.platform == "darwin":
        candidates.append("/Applications/Mixxx.app/Contents/MacOS/mixxx")
    if os.name == "nt" and os.environ.get("PROGRAMFILES"):
        candidates.append(str(Path(os.environ["PROGRAMFILES"], "Mixxx", "mixxx.exe")))
    executable = next((path for path in candidates if path and Path(path).is_file()), None)
    if not executable:
        raise ValueError("Mixxx was not found. Install it from https://mixxx.org/download/ or add mixxx to PATH.")
    subprocess.Popen([executable, *map(str, sources)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Opened Mixxx with {len(sources)} local tracks. Use its mixer and recording controls."


class DJSession:
    def __init__(self, recording_directory, ffmpeg=None, output_factory=default_output):
        self.directory = Path(recording_directory)
        self.ffmpeg = ffmpeg
        self.output_factory = output_factory
        self.decks = {}
        self.lock = threading.RLock()
        self.operations = threading.RLock()
        self.output = None
        self.recording = None
        self.last_file = None
        self.crossfader = 0.0
        self.target = 0.0
        self.remaining = 0
        self.output_warnings = 0
        self.peak = 0.0
        self.clipped_frames = 0

    def _start_output(self):
        if self.output is not None:
            return
        stream = None
        try:
            stream = self.output_factory(self.callback)
            stream.start()
        except Exception as error:
            if stream is not None:
                stream.close()
            raise ValueError(f"Could not open the default stereo output at {SAMPLE_RATE} Hz: {error}") from error
        self.output = stream

    def callback(self, outdata, frames, timing, status):
        if status:
            self.output_warnings += 1
        outdata[:] = self.mix(frames)

    def mix(self, frames):
        with self.lock:
            mix = np.zeros((frames, 2), dtype=np.float32)
            if self.remaining:
                ramp = min(self.remaining, frames)
                step = (self.target - self.crossfader) / self.remaining
                levels = np.full(frames, self.target, dtype=np.float64)
                levels[:ramp] = self.crossfader + step * np.arange(1, ramp + 1)
                self.remaining -= ramp
                self.crossfader = float(levels[ramp - 1]) if self.remaining else self.target
                angle = levels[:, None] * (math.pi / 2)
            else:
                angle = self.crossfader * (math.pi / 2)
            if "A" in self.decks:
                mix += self.decks["A"].render(frames) * np.cos(angle)
            if "B" in self.decks:
                mix += self.decks["B"].render(frames) * np.sin(angle)
            np.nan_to_num(mix, copy=False)
            amplitudes = np.abs(mix)
            self.peak = float(amplitudes.max(initial=0.0))
            if self.peak > 1.0:
                self.clipped_frames += int(np.count_nonzero(np.any(amplitudes > 1.0, axis=1)))
            np.clip(mix, -1, 1, out=mix)
            if self.recording:
                self.recording.append(mix)
            return mix

    def unload_source(self, path):
        source = Path(path).expanduser().resolve()
        with self.operations:
            with self.lock:
                removed = [self.decks.pop(name) for name in list(self.decks) if self.decks[name].source == source]
            for deck in removed:
                deck.close()

    def _get(self, name):
        if name not in ("A", "B"):
            raise ValueError("Choose deck A or B.")
        if name not in self.decks:
            raise ValueError(f"Deck {name} is empty. Use dj load {name} FILE.")
        return self.decks[name]

    def status(self):
        with self.lock:
            lines = []
            for name in ("A", "B"):
                deck = self.decks.get(name)
                if not deck:
                    lines.append(f"{name} · empty")
                    continue
                cues = ", ".join(f"{slot}@{frame / SAMPLE_RATE:.2f}s" for slot, frame in sorted(deck.cues.items()))
                loop = "off" if not deck.loop else "–".join(f"{frame / SAMPLE_RATE:.2f}s" for frame in deck.loop)
                title = "".join(char if char.isprintable() else " " for char in deck.source.name)
                lines.append(f"{name} · {title} · {'playing' if deck.playing else 'paused'} · "
                             f"{deck.position / SAMPLE_RATE:.2f}/{len(deck.samples) / SAMPLE_RATE:.2f}s · "
                             f"{deck.gain * 100:g}% · {deck.rate:g}× · loop {loop} · cues {cues or 'none'}")
            recording = self.recording.path if self.recording else "off"
            if self.recording and self.recording.error:
                recording = f"failed ({self.recording.error})"
            level = f"{20 * math.log10(self.peak):.1f}" if self.peak else "−∞"
            lines.append(f"Crossfader {self.crossfader * 100:.1f}% · Peak {level} dBFS · Recording {recording}")
            if self.clipped_frames:
                lines.append(f"Master clipped on {self.clipped_frames} sample frames. Lower the deck gain.")
            if self.output_warnings:
                lines.append(f"Output timing warnings: {self.output_warnings}")
            if self.last_file:
                lines.append(f"Last recording: {self.last_file}")
            return "\n".join(lines)

    def _transport(self, action, name):
        with self.lock:
            decks = list(self.decks.values()) if name == "ALL" else [self._get(name)]
        if action == "play":
            if not decks:
                raise ValueError("Load a deck first.")
            self._start_output()
        with self.lock:
            for deck in decks:
                if action == "stop" or (action == "play" and deck.position >= len(deck.samples)):
                    deck.position = deck.loop[0] if action == "play" and deck.loop else 0
                deck.playing = action == "play"
        return self.status()

    def _edit(self, action, name, values):
        with self.lock:
            deck = self._get(name)
            duration = len(deck.samples) / SAMPLE_RATE
            if action == "gain" and len(values) == 1:
                deck.gain = number(values[0], 0, 200, "Gain (%)") / 100
            elif action == "rate" and len(values) == 1:
                deck.rate = number(values[0], 0.25, 4, "Playback rate")
            elif action == "seek" and len(values) == 1:
                deck.seek(number(values[0], 0, duration, "Position (s)") * SAMPLE_RATE)
            elif action == "loop" and [v.lower() for v in values] == ["off"]:
                deck.loop = None
            elif action == "loop" and len(values) == 2:
                start, end = [round(number(v, 0, duration, "Loop boundary (s)") * SAMPLE_RATE) for v in values]
                if end <= start:
                    raise ValueError("The loop end must follow the start.")
                deck.loop = start, end
                deck.position = start
            elif action == "cue" and len(values) == 2 and values[0].lower() in {"set", "go"}:
                if len(values[1]) != 1 or values[1] not in "12345678":
                    raise ValueError("Choose a cue slot from 1 to 8.")
                slot = int(values[1])
                if values[0].lower() == "set":
                    deck.cues[slot] = deck.position
                elif slot in deck.cues:
                    deck.seek(deck.cues[slot])
                else:
                    raise ValueError(f"Cue {slot} has not been set on deck {name}.")
            else:
                raise ValueError(HELP)
        return self.status()

    def _finish_recording(self):
        with self.lock:
            recorder = self.recording
            self.recording = None
        if not recorder:
            raise ValueError("No DJ recording is active.")
        self.last_file = recorder.finish()
        return f"Saved stereo master: {self.last_file}"

    def _close_output(self):
        if self.output:
            try:
                self.output.stop()
            finally:
                try:
                    self.output.close()
                finally:
                    self.output = None

    def close(self):
        with self.operations:
            try:
                self._close_output()
            finally:
                with self.lock:
                    old_decks, self.decks = self.decks, {}
                    self.crossfader = self.target = 0.0
                    self.remaining = self.output_warnings = self.clipped_frames = 0
                    self.peak = 0.0
                try:
                    if self.recording:
                        self._finish_recording()
                finally:
                    for deck in old_decks.values():
                        deck.close()
        return "DJ decks closed." + (f" Last recording: {self.last_file}" if self.last_file else "")

    def command(self, arguments):
        if not arguments:
            return self.status()
        action, *values = arguments
        action = action.lower()
        with self.operations:
            if action in ("help", "?", "--help"):
                return HELP
            if action == "status" and not values:
                return self.status()
            if action == "close" and not values:
                return self.close()
            if action == "mixxx" and not values:
                if self.recording:
                    raise ValueError("Finish the current DJ recording with dj record stop before opening Mixxx.")
                sources = [self.decks[name].source for name in ("A", "B") if name in self.decks]
                result = launch_mixxx(sources)
                self._transport("pause", "ALL")
                self._close_output()
                return result
            if action == "load" and len(values) >= 2:
                name = values[0].upper()
                if name not in ("A", "B"):
                    raise ValueError("Choose deck A or B.")
                replacement = Deck.load(" ".join(values[1:]), self.ffmpeg)
                with self.lock:
                    old = self.decks.get(name)
                    self.decks[name] = replacement
                if old:
                    old.close()
                return self.status()
            if action in ("play", "pause", "stop") and len(values) == 1:
                return self._transport(action, values[0].upper())
            if action in ("gain", "rate", "seek", "cue", "loop") and values:
                return self._edit(action, values[0].upper(), values[1:])
            if action == "crossfade" and 1 <= len(values) <= 2:
                target = number(values[0], 0, 100, "Crossfade (%)") / 100
                seconds = number(values[1], 0, 600, "Fade duration (s)") if len(values) == 2 else 0
                with self.lock:
                    self.remaining = round(seconds * SAMPLE_RATE)
                    self.target = target
                    if not self.remaining:
                        self.crossfader = target
                return self.status()
            if action == "record" and values:
                operation = values[0].lower()
                if operation == "stop" and len(values) == 1:
                    return self._finish_recording()
                if operation == "start":
                    if self.recording:
                        raise ValueError("A recording is already active.")
                    if len(values) > 1:
                        path = wav_path(" ".join(values[1:]))
                    else:
                        self.directory.mkdir(parents=True, exist_ok=True)
                        path = self.directory / f"mix-{uuid.uuid4().hex[:12]}.wav"
                    self._start_output()
                    recorder = MasterRecording(path)
                    with self.lock:
                        self.recording = recorder
                    return f"Recording stereo master to {path}"
            if action in ("export", "share"):
                if self.recording:
                    raise ValueError("Finish the current recording with dj record stop.")
                if not self.last_file or not self.last_file.is_file():
                    raise ValueError("Make a recording with dj record start and dj record stop first.")
                if action == "share" and not values:
                    from .clip_share import open_share
                    return open_share(self.last_file, recording=True)
                if action == "export":
                    if not values:
                        return str(self.last_file)
                    destination = wav_path(" ".join(values))
                    with self.last_file.open("rb") as source, destination.open("xb") as copy:
                        try:
                            shutil.copyfileobj(source, copy)
                            copy.flush()
                        except BaseException:
                            copy.close()
                            destination.unlink(missing_ok=True)
                            raise
                    return f"Exported stereo master to {destination}"
            raise ValueError(HELP)

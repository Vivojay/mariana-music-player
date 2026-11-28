"""User-initiated local microphone capture with optional offline speech recognition."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import threading
import wave
from bisect import bisect_right
from contextlib import suppress
from datetime import datetime
from html import escape
from pathlib import Path
from uuid import uuid4

from .output_targets import OutputTargetError, bind_output_target

RATE = 16_000
USAGE = """speech record                  Record your microphone locally as WAV.
speech start [MODEL_DIRECTORY]  Record and transcribe with an installed Vosk model.
speech speaker NAME             Label speech from this point in the recording.
speech status | text | live     Inspect capture, read text or watch live in the terminal.
speech stop                     Close the microphone and finish audio and captions.
speech export PATH              Save a new .wav, .vtt or .txt file from the last take.
speech share [wav|vtt|txt]      Share the completed recording or its captions.
speech transcribe OUTPUT       Draft timed captions for the loaded local recording."""


def microphone():
    try:
        import sounddevice
        return sounddevice.RawInputStream(samplerate=RATE, blocksize=1600, channels=1, dtype="int16")
    except (ImportError, OSError) as error:
        raise ValueError("Microphone recording needs sounddevice and PortAudio. See docs/LIVE_SPEECH.md.") from error


def local_recognizer(path):
    setting = path or os.environ.get("MARIANA_VOSK_MODEL")
    if not setting or not Path(setting).expanduser().is_dir():
        raise ValueError("Choose an extracted Vosk model directory with speech start MODEL_DIRECTORY.")
    try:
        from vosk import KaldiRecognizer, Model  # pyright: ignore[reportMissingImports]
    except (ImportError, OSError) as error:
        raise ValueError("Offline transcription requires the optional vosk package. See docs/LIVE_SPEECH.md.") from error
    try:
        engine = KaldiRecognizer(Model(str(Path(setting).expanduser())), RATE)
        engine.SetWords(True)
        return engine
    except Exception as error:
        raise ValueError(f"Could not open the Vosk model in {setting}.") from error


def timestamp(seconds):
    millis = round(seconds * 1000)
    minutes, rest = divmod(millis, 60_000)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{rest // 1000:02}.{rest % 1000:03}"


class Take:
    def __init__(self, path, stream, engine):
        self.path = path
        self.stream = stream
        self.engine = engine
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.aborting = threading.Event()
        self.done = threading.Event()
        self.frames = 0
        self.cues = []
        self.partial = ""
        self.error = ""
        self.labels = [(0.0, "Speaker")]
        self.worker = threading.Thread(target=self.capture, name="mariana-speech", daemon=True)

    def label(self, name):
        name = " ".join(name.split())
        if not name or len(name) > 80:
            raise ValueError("Choose a speaker label of 1–80 characters.")
        with self.lock:
            self.labels.append((self.frames / RATE, name))

    def result(self, encoded):
        row = json.loads(encoded)
        words = " ".join(row.get("text", "").split())
        with self.lock:
            self.partial = ""
            if not words:
                return
            tokens = row.get("result") or []
            prior_end = self.cues[-1][1] if self.cues else 0.0
            duration = self.frames / RATE
            start = float(tokens[0]["start"]) if tokens else prior_end
            end = float(tokens[-1]["end"]) if tokens else duration
            if not math.isfinite(start) or not math.isfinite(end) or duration <= 0:
                return
            start = min(max(0.0, start), max(0.0, duration - .001))
            end = min(duration, max(start + .001, end))
            # A recognizer may finalize an earlier utterance after the operator changes speakers.
            index = bisect_right(self.labels, start, key=lambda pair: pair[0]) - 1
            self.cues.append((start, end, self.labels[index][1], words))

    def render(self, suffix):
        with self.lock:
            if suffix == ".txt":
                return "\n".join(f"{who}: {text}" for _, _, who, text in self.cues) + "\n"
            entries = [f"{timestamp(start)} --> {timestamp(end)}\n<v {escape(who)}>{escape(text)}</v>"
                       for start, end, who, text in self.cues]
            return "WEBVTT\n\n" + "\n\n".join(entries) + "\n"

    def capture(self):
        try:
            with wave.open(str(self.path), "wb") as audio:
                audio.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
                while not self.stopping.is_set():
                    data, overflow = self.stream.read(1600)
                    if overflow:
                        raise ValueError("Microphone overflow interrupted the take.")
                    block = bytes(data)
                    if not block or len(block) % 2:
                        raise ValueError("The microphone stopped returning complete samples.")
                    if (self.frames * 2 + len(block)) > 0xFFFFFFFF - 36:
                        raise ValueError("WAV reached its format limit. Start a new take.")
                    audio.writeframesraw(block)
                    with self.lock:
                        self.frames += len(block) // 2
                    if self.engine:
                        if self.engine.AcceptWaveform(block):
                            self.result(self.engine.Result())
                        else:
                            partial = json.loads(self.engine.PartialResult()).get("partial", "")
                            with self.lock:
                                self.partial = partial
        except Exception as error:
            if not self.aborting.is_set():
                self.error = str(error)
        finally:
            try:
                if self.engine:
                    self.result(self.engine.FinalResult())
                if self.cues:
                    for suffix in (".vtt", ".txt"):
                        with self.path.with_suffix(suffix).open("x", encoding="utf-8") as out:
                            out.write(self.render(suffix))
            except Exception as error:
                self.error = f"{self.error} Could not finish the captions: {error}".strip()
            finally:
                with suppress(Exception):
                    self.stream.close()
                self.engine = None
                self.done.set()

    def stop(self):
        self.stopping.set()
        if not self.done.wait(1):
            self.aborting.set()
            with suppress(Exception):
                self.stream.abort()
            if not self.done.wait(4):
                raise ValueError("The microphone is still closing. Check speech status before exporting.")

    def status(self):
        with self.lock:
            state = "Stopped" if self.done.is_set() else "Recording microphone"
            if self.engine is not None:
                state += " with offline captions"
            message = f"{state} · {self.frames / RATE:.1f}s · {len(self.cues)} captions · {self.path}"
            return f"{message}\nCapture interrupted: {self.error}" if self.error else message

    def text(self):
        with self.lock:
            if not self.engine and not self.cues:
                return "No captions."
            lines = [self.render(".txt").rstrip(), self.partial]
            return "\n".join(x for x in lines if x) or "Waiting for speech."


class SpeechCapture:
    def __init__(self, folder, *, input_factory=microphone, model_factory=local_recognizer):
        self.folder = Path(folder)
        self.input_factory = input_factory
        self.model_factory = model_factory
        self.lock = threading.RLock()
        self.take = None

    def start(self, transcribe=False, model=None):
        with self.lock:
            if self.take and not self.take.done.is_set():
                raise ValueError("The microphone is already in use. Use speech stop first.")
            engine = self.model_factory(model) if transcribe else None
            self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = self.folder / f"Mariana-speech-{stamp}-{uuid4().hex[:8]}.wav"
            stream = None
            try:
                stream = self.input_factory()
                stream.start()
                take = Take(path, stream, engine)
                take.worker.start()
                self.take = take
            except Exception as error:
                if stream is not None:
                    with suppress(Exception):
                        stream.close()
                raise ValueError(f"Could not start the microphone: {error}") from error
            return take.status()

    def close(self):
        with self.lock:
            if self.take:
                self.take.stop()

    def export(self, take, destination):
        if not take.done.is_set():
            raise ValueError("Use speech stop before exporting.")
        suffix = Path(destination).suffix.lower()
        if suffix not in {".wav", ".vtt", ".txt"}:
            raise ValueError("Choose a .wav, .vtt or .txt filename.")
        if not take.frames or (suffix != ".wav" and not take.cues):
            raise ValueError("This take has no audio or captions for that format.")
        try:
            target = bind_output_target(destination)
            if target.existed:
                raise ValueError("The destination already exists. Choose a new filename.")
            with tempfile.TemporaryDirectory(dir=target.path.parent) as folder:
                stage = Path(folder) / ("take" + suffix)
                if suffix == ".wav":
                    shutil.copyfile(take.path, stage)
                else:
                    stage.write_text(take.render(suffix), encoding="utf-8")
                return str(target.activate(stage))
        except OutputTargetError as error:
            raise ValueError(str(error)) from error

    def command(self, args):
        action, rest = (args[0].casefold(), args[1:]) if args else ("status", [])
        with self.lock:
            if action in {"help", "?"}:
                return USAGE
            if action == "record" and not rest:
                return self.start()
            if action == "start" and len(rest) <= 1:
                return self.start(True, rest[0] if rest else None)
            take = self.take
            if take is None:
                return "Microphone off. Use speech record or speech start MODEL_DIRECTORY."
            if action == "speaker" and rest and not take.done.is_set():
                take.label(" ".join(rest))
                return "Speaker label set for the next utterance."
            if action == "status" and not rest:
                return take.status()
            if action == "stop" and not rest:
                take.stop()
                return take.status()
            if action == "text" and not rest:
                return take.text()
            if action == "export" and len(rest) == 1:
                return "Exported " + self.export(take, rest[0])
            if action == "share" and len(rest) <= 1:
                if not take.done.is_set() or not take.frames:
                    raise ValueError("Stop a microphone recording before sharing it.")
                from .clip_share import open_share
                suffix = "." + rest[0].casefold() if rest else ".wav"
                if suffix not in {".wav", ".vtt", ".txt"}:
                    raise ValueError("Use speech share wav, vtt or txt.")
                if suffix != ".wav" and not take.cues:
                    raise ValueError("This take has no captions.")
                return open_share(take.path.with_suffix(suffix), recording=True)
            raise ValueError(USAGE)


def show_live(take, appearance, *, input=None, output=None):
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    from .terminal_view import TerminalView
    from .theme_palette import resolved_theme

    if take is None or take.engine is None:
        raise ValueError("Start offline captions with speech start MODEL_DIRECTORY first.")
    view = TerminalView()
    keys = KeyBindings()

    @keys.add("q")
    @keys.add("escape")
    @keys.add("c-c")
    def leave(event):
        view.finish()

    @keys.add("s")
    def stop(event):
        view.finish("stop")

    def render():
        with take.lock:
            lines = [f"{who}: {text}" for _, _, who, text in take.cues[-6:]]
            lines.append(take.partial)
            return "\n\n".join([take.status(), *lines, "S  Stop microphone     Q  Return to Mariana"])

    colors = resolved_theme(appearance)["chrome"]
    style = Style.from_dict({"": f"bg:{colors['background'][:7]} {colors['text'][:7]}"})
    caption = Window(FormattedTextControl(render, focusable=True), wrap_lines=True)
    if view.run(caption, focus=caption, bindings=keys, style=style, interval=.2, input=input, output=output) == "stop":
        take.stop()

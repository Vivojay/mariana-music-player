"""Controls for live output effects, explicit microphone monitoring, and WAV bounces."""
from __future__ import annotations

from dataclasses import asdict
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

import numpy as np

from .effect_packages import SUFFIXES, install_package, resolve_package
from .effects import EffectProcessor, LIMITS, PRESETS, Rack, setting


def _make(rack, rate):
    return None if rack == Rack() else EffectProcessor(rack, rate)


class EffectStudio:
    def __init__(self, engine, ffmpeg, directory):
        self.engine = engine
        self.ffmpeg = ffmpeg
        self.directory = Path(directory)
        self.plugin_directory = self.directory.parent / "plugins"
        self.rack = Rack()
        self.mic_processor = None
        self.mic = None
        self.lock = threading.RLock()

    def close(self):
        with self.lock:
            stream, self.mic = self.mic, None
            if stream is not None:
                try:
                    stream.abort()
                finally:
                    stream.close()
            self.mic_processor = None

    def restore_processor(self):
        with self.lock:
            self.engine().monitor_effect = _make(self.rack, 48000)

    def _install(self, rack):
        with self.lock:
            prepared = _make(rack, 48000)
            mic = _make(rack, 48000) if self.mic is not None else None
            self.engine().monitor_effect = prepared
            self.mic_processor = mic
            self.rack = rack

    def _mic_start(self):
        if self.mic is not None:
            return
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise ValueError("Microphone monitoring requires sounddevice and PortAudio.") from exc
        self.mic_processor = _make(self.rack, 48000)

        def callback(indata, outdata, frames, timing, status):
            monitor = self.mic_processor
            samples = np.repeat(indata[:, :1], 2, axis=1)
            outdata[:] = (monitor.process(samples) if monitor else samples) * .35

        stream = None
        try:
            stream = sd.Stream(samplerate=48000, dtype="float32", channels=(1, 2),
                               callback=callback, blocksize=512)
            stream.start()
        except Exception as exc:
            if stream is not None:
                stream.close()
            self.mic_processor = None
            raise ValueError("Could not open the default microphone and stereo output at 48 kHz. Check device access and availability.") from exc
        self.mic = stream

    def status(self):
        values = ", ".join(f"{k} {v:g}" for k, v in asdict(self.rack).items() if v)
        fault = any(p is not None and p.fault for p in (self.engine().monitor_effect, self.mic_processor))
        return (f"Output FX: {values or 'dry'} · microphone: {'monitoring' if self.mic is not None else 'off'}"
                + (" · processing fault, affected output bypassed" if fault else ""))

    def command(self, args):
        if not args or args == ["status"]:
            return self.status()
        if args in (["help"], ["?"]):
            return ("fx presets | fx preset NAME | fx set EFFECT VALUE | fx save/load NAME | fx off | fx mic on/off | "
                    "fx tempo RATE INPUT OUTPUT.wav | fx plugins | fx plugin PLUGIN_OR_NAME INPUT OUTPUT.wav\n"
                    "fx plugin install NAME ZIP_OR_HTTPS_URL SHA256\n"
                    "Controls (percent, except pitch in semitones): " + ", ".join(LIMITS))
        if args == ["plugins"]:
            packages = []
            if self.plugin_directory.is_dir():
                packages = sorted(path.name for path in self.plugin_directory.iterdir()
                                  if resolve_package(self.plugin_directory, path.name))
            return ("Installed for this profile: " + (" · ".join(packages) or "none")
                    + "\nUse fx plugin install NAME ZIP_OR_HTTPS_URL SHA256 to add a vendor package. "
                    "Use fx plugin NAME INPUT OUTPUT.wav to render it offline.")
        if len(args) == 5 and args[:2] == ["plugin", "install"]:
            _, _, name, source, digest = args
            install_package(self.plugin_directory, name, source, digest)
            return f"Installed {name} for this profile. Run fx plugin {name} INPUT OUTPUT.wav to render."
        if args == ["presets"]:
            saved = sorted(path.stem for path in self.directory.glob("*.json")
                           if path.is_file() and re.fullmatch("[a-z0-9][a-z0-9-]{0,39}", path.stem))
            return "Factory: " + " · ".join(PRESETS) + ("\nSaved: " + " · ".join(saved) if saved else "")
        if len(args) == 2 and args[0] in {"save", "load"}:
            if not re.fullmatch("[a-z0-9][a-z0-9-]{0,39}", args[1]):
                raise ValueError("Use a rack name of 1–40 lowercase letters, digits or hyphens.")
            path = self.directory / (args[1] + ".json")
            try:
                if args[0] == "save":
                    self.directory.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory(dir=self.directory) as tmp:
                        stage = Path(tmp) / "rack.json"
                        stage.write_text(json.dumps(asdict(self.rack)), encoding="utf-8")
                        stage.replace(path)
                    return f"Saved rack {args[1]}"
                if path.stat().st_size > 4096:
                    raise ValueError("Invalid rack file.")
                saved = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(saved, dict) or any(k not in LIMITS or type(v) not in (int,float) for k,v in saved.items()):
                    raise ValueError("Invalid rack file.")
                rack = Rack()
                for key, value in saved.items():
                    rack = setting(rack, key, str(value))
                self._install(rack)
                return self.status()
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"Cannot {args[0]} this rack: {exc}") from exc
        if args == ["off"]:
            self._install(Rack())
        elif len(args) == 2 and args[0] == "preset":
            if args[1] not in PRESETS:
                raise ValueError("Unknown rack preset. Try fx presets.")
            self._install(PRESETS[args[1]])
        elif len(args) == 3 and args[0] == "set":
            with self.lock:
                self._install(setting(self.rack, args[1], args[2]))
        elif args == ["mic", "on"]:
            with self.lock:
                self._mic_start()
        elif args == ["mic", "off"]:
            self.close()
        elif len(args) == 4 and args[0] in {"tempo", "plugin"}:
            return self._render(*args)
        else:
            raise ValueError("Unknown sound design command. Use fx help.")
        return self.status()

    def _render(self, kind, value, source, target):
        source, target = Path(source).expanduser().resolve(), Path(target).expanduser().resolve()
        if not source.is_file() or not target.parent.is_dir() or target.suffix.lower() != ".wav":
            raise ValueError("Choose an existing input file and a .wav output in an existing directory.")
        if target.exists():
            raise ValueError("Output already exists. Choose a new WAV filename.")
        environment = None
        if kind == "tempo":
            try:
                speed = float(value)
                if not .5 <= speed <= 2:
                    raise ValueError
            except ValueError:
                raise ValueError("Tempo must be between 0.5 and 2.0.") from None
            args = [self.ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source),
                    "-map", "0:a:0", "-vn", "-af", f"atempo={speed}", "-c:a", "pcm_s16le"]
        else:
            plugin = resolve_package(self.plugin_directory, value) or Path(value).expanduser().resolve()
            if not plugin.exists() or plugin.suffix.lower() not in SUFFIXES:
                raise ValueError("Choose an installed plug-in name, a .vst3 path, or a macOS .component path.")
            helper, environment = _plugin_host()
            args = [*helper, str(plugin), str(source)]
        try:
            with tempfile.TemporaryDirectory(prefix=".mariana-fx-", dir=target.parent) as work:
                bounced = Path(work) / "bounce.wav"
                completed = subprocess.run([*args, str(bounced)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, timeout=600,
                                           cwd=Path(__file__).resolve().parents[1], env=environment,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if completed.returncode or not bounced.is_file() or bounced.stat().st_size <= 44:
                    raise ValueError(f"{kind.title()} render failed. Check that the input format and effect are supported.")
                # Install a complete WAV atomically where hard links are available.
                try:
                    os.link(bounced, target)
                except FileExistsError:
                    raise
                except OSError:
                    with target.open("xb") as out:
                        try:
                            with bounced.open("rb") as data:
                                shutil.copyfileobj(data, out)
                        except BaseException:
                            out.close()
                            target.unlink(missing_ok=True)
                            raise
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Rendering timed out. Try a shorter input.") from exc
        except OSError as exc:
            raise ValueError(f"Could not write the effect render: {exc}") from exc
        return f"Saved {target}"


def _plugin_host():
    configured = os.environ.get("MARIANA_PLUGIN_PYTHON")
    frozen = getattr(sys, "frozen", False)
    if configured:
        python = Path(configured).expanduser().resolve()
        if not python.is_file():
            raise ValueError("Point MARIANA_PLUGIN_PYTHON at an installed Python executable with Pedalboard.")
        runner = Path(__file__).resolve().with_name("effect_plugin.py")
        if not runner.is_file():
            raise ValueError("This build lacks the external plug-in helper. Use a newer build or the source checkout.")
        env = os.environ.copy()
        if frozen:
            original = env.pop("LD_LIBRARY_PATH_ORIG", None)
            if original is not None:
                env["LD_LIBRARY_PATH"] = original
            else:
                env.pop("LD_LIBRARY_PATH", None)
        return [str(python), "-I", str(runner)], env
    if frozen:
        raise ValueError("Plug-in rendering is optional. Set MARIANA_PLUGIN_PYTHON to a Python environment with Pedalboard.")
    if importlib.util.find_spec("pedalboard") is None:
        raise ValueError("Plug-in rendering requires the optional Pedalboard package. See docs/SOUND_DESIGN.md.")
    return [sys.executable, "-m", "mariana.effect_plugin"], None

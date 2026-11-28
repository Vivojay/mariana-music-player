"""Muted, independently closable picture window driven by Mariana's playback clock."""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .video_detection import LiveDetection
from .video_filters import DEFAULT as DEFAULT_FILTER
from .video_filters import filter_image, parse_filter

FPS = 25
# CachedVideoProxy creates its token with secrets.token_urlsafe(24).
_PROXY = re.compile(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})/[A-Za-z0-9_-]{32}/media")


def _input_protocols(source):
    match = _PROXY.fullmatch(source)
    if match and int(match[1]) <= 65535:
        return "http,tcp"
    if "://" not in source and Path(source).is_absolute() and Path(source).is_file():
        return "file"
    raise ValueError("Unavailable picture source")


def _size(width, height, limits=(1280, 720)):
    scale = min(1.0, limits[0] / max(1, width), limits[1] / max(1, height))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def _event(event, **kwargs):
    with contextlib.suppress(BrokenPipeError, OSError):
        print(json.dumps({"event": event, **kwargs}, ensure_ascii=True), flush=True)


@dataclass(frozen=True)
class Clock:
    position: float
    sampled_at: float
    rate: float

    @classmethod
    def read(cls, sample, now):
        position = float(sample["position"])
        when = float(sample.get("sampled_at", now))
        speed = float(sample.get("rate", 1))
        if not all(map(math.isfinite, (position, when, speed))):
            raise ValueError("Invalid clock")
        return cls(max(0., position), min(now, when), max(0., speed) if sample["state"] == "playing" else 0.)

    def at(self, now):
        # Hold the last authoritative clock if the host stops sending heartbeats.
        return self.position + min(.4, max(0., now - self.sampled_at)) * self.rate

    def jumped(self, previous):
        tolerance = .14 if previous.rate else .5 / FPS
        return abs(self.position - previous.at(self.sampled_at)) > tolerance


class PictureBudget:
    """Reduce decode cost when successive delivered frames cannot keep pace with audio."""
    def __init__(self):
        self.level = 0
        self.behind_since = None

    def limits(self):
        return (1280 >> self.level, 720 >> self.level)

    def should_downsize(self, delay, now):
        if delay < .30:
            self.behind_since = None
        elif self.behind_since is None:
            self.behind_since = now
        elif self.level < 2 and now - self.behind_since >= 1.25:
            self.level += 1
            self.behind_since = None
            return True
        return False


class Decoder:
    """Backpressure at the picture clock; retain just the newest frame ready to paint."""
    def __init__(self, executable, source, start, size: tuple[int, int]):
        self.size = size
        self.start = start
        self.target = start
        self.condition = threading.Condition()
        self.process = None
        self.closed = False
        self.error = False
        self.exhausted = False
        self.frame = None
        self.thread = threading.Thread(target=self._decode, args=(executable, source), daemon=True)
        self.thread.start()

    def advance(self, target):
        with self.condition:
            self.target = target
            self.condition.notify()
            frame, self.frame = self.frame, None
            return frame

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify()
            if self.process is not None:
                self.process.kill()

    def _decode(self, executable, source):
        width, height = self.size
        process = None
        output = None
        try:
            protocols = _input_protocols(source)
            filters = (f"fps={FPS}:start_time=0,scale=w='min({width},max(1,round({height}*dar)))':"
                       f"h='min({height},max(1,round({width}/dar)))',setsar=1,"
                       f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
            args = [executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist",
                    protocols, "-format_whitelist", "mov,mp4,matroska,webm", "-ss", f"{self.start:.6f}",
                    "-i", source, "-map", "0:v:0", "-an", "-sn", "-dn", "-filter_threads", "1",
                    "-vf", filters, "-threads", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
            # The only network endpoint is Mariana's own range server. Never route its
            # capability through a proxy configured for unrelated Internet traffic.
            env = dict(os.environ, no_proxy="127.0.0.1", NO_PROXY="127.0.0.1")
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, env=env,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            output = process.stdout
            if output is None:
                raise OSError("FFmpeg picture output is unavailable.")
            with self.condition:
                if self.closed:
                    return
                self.process = process
            count = width * height * 3
            index = 0
            while True:
                raw = output.read(count)
                if len(raw) != count:
                    self.error = process.wait() != 0 or index == 0
                    self.exhausted = True
                    return
                stamp = self.start + index / FPS
                with self.condition:
                    self.condition.wait_for(lambda frame_time=stamp: self.closed or frame_time <= self.target + .5 / FPS)
                    if self.closed:
                        return
                    self.frame = (stamp, raw)
                index += 1
        except (OSError, ValueError):
            self.error = True
        finally:
            if process is not None:
                process.kill()
                if output is not None:
                    output.close()
                process.wait()
            with self.condition:
                self.process = None


class Inbox:
    def __init__(self):
        self.latest = None
        self.ended = threading.Event()

    def read(self):
        try:
            for line in sys.stdin.buffer:
                sample = json.loads(line)
                if not isinstance(sample, dict):
                    break
                self.latest = sample
        except (OSError, UnicodeError, ValueError):
            pass
        finally:
            self.ended.set()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True)
    args = parser.parse_args(argv)
    try:
        import tkinter as tk

        from PIL import Image, ImageTk
    except ImportError:
        _event("error", code="dependency", message="The video window needs Tk and Pillow.", fatal=True)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        _event("error", code="display", message="No graphical display is available.", fatal=True)
        return 1

    root.title("Mariana Video")
    root.geometry("800x450")
    root.minsize(180, 110)
    canvas = tk.Canvas(root, background="#08090c", highlightthickness=0)
    canvas.pack(expand=True, fill="both")
    picture = canvas.create_image(0, 0, anchor="center")
    message = canvas.create_text(0, 0, text="Preparing video…", fill="white", justify="center")
    caption = tk.Label(canvas, bg="#141414", fg="white", font=("TkDefaultFont", 14),
                       padx=8, pady=3, justify="center")
    inbox = Inbox()
    threading.Thread(target=inbox.read, name="video-clock", daemon=True).start()
    decoder = None
    previous = clock = identity = None
    last_size = render_size = None
    resized = 0.
    budget = PictureBudget()
    photo = shown_at = last_frame = None
    selection = drawn_filter = DEFAULT_FILTER
    announced = reported = False
    detector = None
    detector_setting = (0, None)
    detection_status = None
    overlay_epoch = 0
    latest_probe = None
    overlay_drawn = None
    last_offer = 0.

    def reset():
        nonlocal decoder, photo, shown_at, last_frame, reported, announced
        nonlocal overlay_epoch
        if decoder is not None:
            decoder.close()
            decoder = None
        canvas.itemconfigure(picture, image="")
        canvas.delete("detections")
        overlay_epoch += 1
        photo = shown_at = last_frame = None
        announced = reported = False

    def tick():
        nonlocal decoder, previous, identity, clock, photo, shown_at, last_size, render_size, resized
        nonlocal reported, announced, budget, last_frame, selection, drawn_filter
        nonlocal detector, detector_setting, detection_status, overlay_drawn, latest_probe, last_offer
        if inbox.ended.is_set():
            root.destroy()
            return
        now = time.monotonic()
        sample = inbox.latest
        width, height = canvas.winfo_width(), canvas.winfo_height()
        canvas.coords(picture, width // 2, height // 2)
        canvas.coords(message, width // 2, height // 2)
        size = _size(width, height, budget.limits())
        if size != last_size:
            last_size, resized = size, now
            caption.configure(wraplength=max(100, width - 36))
        if render_size != size and (render_size is None or now - resized > .2):
            reset()
            render_size = size
        if sample is not None:
            if sample is not previous:
                new_clock = Clock.read(sample, now)
                key = (sample.get("source"), sample.get("media_id"), sample.get("revision"))
                if key != identity or (clock is not None and new_clock.jumped(clock)):
                    reset()
                    budget.behind_since = None
                if identity is not None and key[1] != identity[1]:
                    budget = PictureBudget()
                identity, clock, previous = key, new_clock, sample
                effect = sample.get("filter")
                if isinstance(effect, dict):
                    try:
                        preset = effect.get("preset")
                        selection = parse_filter(preset, effect.get("threshold") if preset == "threshold" else None)
                    except ValueError:
                        selection = DEFAULT_FILTER
                model = sample.get("detector")
                if isinstance(model, dict) and type(model.get("version")) is int:
                    path = model.get("path")
                    if path is None or isinstance(path, str):
                        detector_setting = (model["version"], path)
                        if path and detector is None:
                            detector = LiveDetection()
                        if detector:
                            detector.select(*detector_setting)
                title = str(sample.get("title") or "").strip()
                root.title("Mariana Video" + (" — " + title if title else ""))
                text = sample.get("caption")
                if text and sample.get("source"):
                    caption.configure(text=text)
                    caption.place(relx=.5, rely=.95, anchor="s")
                else:
                    caption.place_forget()
            source = sample.get("source")
            if source and clock is not None and sample.get("state") != "idle":
                target = clock.at(now)
                if decoder is None:
                    decoder = Decoder(args.ffmpeg, source, target, render_size or size)
                frame = decoder.advance(target)
                if frame is not None:
                    stamp, raw = frame
                    if budget.should_downsize(target - stamp, now):
                        reset()
                        last_size = render_size = _size(width, height, budget.limits())
                        root.after(12, guarded_tick)
                        return
                    # Never paint obsolete frames while the decoder catches up after a seek.
                    if abs(target - stamp) <= .18:
                        last_frame = frame
                    else:
                        frame = None
                if last_frame is not None and (frame is not None or selection != drawn_filter):
                    stamp, raw = last_frame
                    img = filter_image(Image.frombytes("RGB", decoder.size, raw), selection)
                    display_size = _size(width, height, (2560, 1440))
                    if decoder.size != display_size:
                        img = img.resize(display_size, Image.Resampling.BILINEAR)
                    photo = ImageTk.PhotoImage(img)
                    shown_at = stamp
                    drawn_filter = selection
                    if not announced:
                        _event("showing")
                        announced = True
                    canvas.itemconfigure(picture, image=photo)
                if shown_at is not None and not decoder.exhausted and target - shown_at > .30:
                    # The CPU or network may be stalled. Hide stale pictures until
                    # the decoder delivers a frame near the authoritative playhead.
                    canvas.itemconfigure(picture, image="")
                    photo = shown_at = last_frame = None
                if (detector and detector.snapshot()[0] == "ready" and last_frame is not None
                        and detector_setting[1] and now - last_offer >= .25):
                    stamp, raw = last_frame
                    sample_key = (detector_setting[0], overlay_epoch, stamp)
                    if sample_key != latest_probe and detector.offer(Image.frombytes("RGB", decoder.size, raw), overlay_epoch, stamp):
                        latest_probe, last_offer = sample_key, now
                if decoder.error and not reported:
                    reported = True
                    _event("error", code="decoder", message="FFmpeg could not decode this picture.", fatal=False)
                notice = "Picture unavailable" if reported else ("" if photo is not None else "Synchronizing…")
            else:
                if decoder is not None:
                    reset()
                notice = str(sample.get("message") or "Waiting for video…")
            canvas.itemconfigure(message, text=notice, width=max(100, width - 36))
            if detector:
                state, result = detector.snapshot()
                status = (detector_setting[0], state)
                if status != detection_status:
                    _event("detector", version=status[0], state=status[1])
                    detection_status = status
                if (not source or last_frame is None or not result or result[0] != overlay_epoch
                        or abs(target - result[1]) > .75):
                    result = None
                displayed = (result, width, height, overlay_epoch)
                if displayed != overlay_drawn:
                    canvas.delete("detections")
                    overlay_drawn = displayed
                    if result:
                        frame_width, frame_height = _size(width, height, (2560, 1440))
                        left, top = (width - frame_width) / 2, (height - frame_height) / 2
                        for _category, label, confidence, (x0, y0, x1, y1) in result[2]:
                            x, y = left + x0 * frame_width, top + y0 * frame_height
                            canvas.create_rectangle(x, y, left + x1 * frame_width, top + y1 * frame_height,
                                                    outline="#f4df68", width=2, tags="detections")
                            canvas.create_text(x + 4, y + 2, text=f"{label} {confidence:.0%}", anchor="nw",
                                               fill="#f4df68", font=("TkDefaultFont", 10, "bold"), tags="detections")
        root.after(12, guarded_tick)

    def guarded_tick():
        try:
            tick()
        except (TypeError, ValueError, KeyError, OSError, tk.TclError):
            _event("error", code="decoder", message="Unable to display the picture.", fatal=True)
            root.destroy()

    # Tk drives all drawing. The control and decoder threads never call into Tk.
    root.bind("<Escape>", lambda _event: root.destroy())
    root.after_idle(guarded_tick)
    def mapped(event):
        if event.widget is root:
            root.unbind("<Map>", map_binding)
            root.lift()
            _event("ready")

    map_binding = root.bind("<Map>", mapped)
    try:
        root.mainloop()
    finally:
        if decoder is not None:
            decoder.close()
            decoder.thread.join(timeout=1)
        _event("closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

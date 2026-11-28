"""A polyphonic, live keyboard on the OS audio output. Keys stop on focus loss or parent exit."""
from __future__ import annotations

import atexit
import contextlib
import queue
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

from .tone_procedures import TABLE_SIZE, VOICES, _table

KEYS = "awsedftgyhujk"
NAMES = ("C4","C♯4","D4","D♯4","E4","F4","F♯4","G4","G♯4","A4","A♯4","B4","C5")
_process = None
_lock = threading.RLock()


def close_keys():
    global _process
    with _lock:
        child, _process = _process, None
        if child is not None:
            if child.stdin is not None:
                with contextlib.suppress(OSError):
                    child.stdin.close()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            if child.stdout is not None:
                child.stdout.close()


def open_keys(voice, device=None):
    # A delayed startup or failed replacement may only close its own keyboard.
    with _lock:
        return _open_keys(voice, device)


def _open_keys(voice, device):
    global _process
    if voice not in VOICES or VOICES[voice]["noise"]:
        raise ValueError("Choose a melodic voice from 'tone voices'. Audition percussion with 'tone sfx'.")
    close_keys()
    argv = ([sys.executable, "--mariana-tone-keys"] if getattr(sys,"frozen",False)
            else [sys.executable, "-m", "mariana.tone_keys"])
    if device is not None:
        argv += ["--device", str(device)]
    try:
        child = subprocess.Popen([*argv,voice], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, cwd=Path(__file__).resolve().parents[1],
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as error:
        raise ValueError("Could not start the keyboard window.") from error
    _process = child
    output = child.stdout
    if output is None:
        close_keys()
        raise ValueError("Could not read the keyboard window status.")
    ready = queue.SimpleQueue()
    threading.Thread(target=lambda: ready.put(output.readline(180)), daemon=True).start()
    try:
        message = ready.get(timeout=7).decode("ascii","replace").strip()
    except queue.Empty:
        message = "Keyboard startup timed out."
    if message != "ready":
        close_keys()
        raise ValueError(message or "The keyboard could not open the display or output device.")
    return "Keyboard open. Hold A through K to play. Escape closes it."


atexit.register(close_keys)


class KeyboardMixer:
    def __init__(self, voice, rate):
        self.voice = VOICES[voice]
        self.rate = rate
        self.pressed = queue.SimpleQueue()
        self.active = {}
        self.hz = [440 * 2**((60+i-69)/12) for i in range(13)]
        self.tables = [_table(voice, min(len(self.voice["partials"]), max(1,int(rate*.48/hz)))) for hz in self.hz]

    def fill(self, output):
        while True:
            try:
                index, pressed = self.pressed.get_nowait()
            except queue.Empty:
                break
            if pressed:
                self.active[index] = (0, None)
            elif index in self.active:
                age, release = self.active[index]
                if release is None:
                    self.active[index] = (age,age)
        times = np.arange(len(output))
        signal = np.zeros(len(output))
        for i, (age, release) in list(self.active.items()):
            t = (age + times)/self.rate
            voice = self.voice
            env = np.minimum(1,t/voice["attack"]) * (voice["sustain"] +
                  (1-voice["sustain"])*np.exp(-np.maximum(0,t-voice["attack"])/voice["decay"]))
            if release is not None:
                env *= np.clip(1-(age+times-release)/(self.rate*voice["release"]),0,1)
            phase = (t*self.hz[i]%1)*TABLE_SIZE
            idx = phase.astype(int)
            table = self.tables[i]
            signal += .14*env*(table[idx]+(table[idx+1]-table[idx])*(phase-idx))
            age += len(times)
            if release is not None and age-release >= self.rate * voice["release"]:
                del self.active[i]
            else:
                self.active[i] = (age,release)
        output[:] = np.tanh(signal)[:,None]


def main(args=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--device",type=int)
    parser.add_argument("voice",choices=VOICES)
    args = parser.parse_args(args)
    try:
        import tkinter as tk

        import sounddevice as sd
        root = tk.Tk()
        rate = round(sd.query_devices(args.device, "output")["default_samplerate"])
        mixer = KeyboardMixer(args.voice,rate)
        stream = sd.OutputStream(channels=1,dtype="float32",device=args.device,samplerate=rate,
                                 callback=lambda out,_n,_t,_s: mixer.fill(out))
        stream.start()
    except Exception:
        print("Keyboard needs Tk, a graphical display and an available audio output.",flush=True)
        return 1
    root.title("Mariana Keys")
    tk.Label(root,text=args.voice + "   |   Hold A–K to play, Escape to close",padx=12,pady=8).pack()
    keyboard = tk.Frame(root)
    keyboard.pack(fill="both",expand=True)
    held, buttons, pending = set(), [], {}
    def set_key(i, source, down):
        token = i,source
        was = any(key[0]==i for key in held)
        if down:
            held.add(token)
        else:
            held.discard(token)
        now = any(key[0]==i for key in held)
        if was != now:
            mixer.pressed.put((i,now))
            buttons[i].configure(relief="sunken" if now else "raised")
    for i,note in enumerate(NAMES):
        black = "♯" in note
        key = tk.Button(keyboard,text=note+"\n"+KEYS[i].upper(),fg="white" if black else "#222222",
                        bg="#272933" if black else "#eeeade",width=3,pady=15)
        key.pack(side="left",fill="both",expand=True)
        key.bind("<ButtonPress-1>",lambda _e,i=i:set_key(i,"pointer",True))
        key.bind("<ButtonRelease-1>",lambda _e,i=i:set_key(i,"pointer",False))
        buttons.append(key)
    def handle(event,down):
        char = event.keysym.lower()
        if len(char)!=1 or char not in KEYS:
            return
        i = KEYS.index(char)
        if i in pending:
            root.after_cancel(pending.pop(i))
        if down:
            set_key(i,"key",True)
        else:
            # X11 auto-repeat emits a release followed by another press.
            pending[i] = root.after_idle(lambda:(pending.pop(i,None),set_key(i,"key",False)))
    def silence(_event):
        for i,source in tuple(held):
            set_key(i,source,False)
    root.bind("<KeyPress>",lambda e:handle(e,True))
    root.bind("<KeyRelease>",lambda e:handle(e,False))
    root.bind("<FocusOut>",silence)
    root.bind("<Escape>",lambda _e:root.destroy())
    ended = threading.Event()
    def watch_parent():
        try:
            sys.stdin.buffer.read(1)
        finally:
            ended.set()
    threading.Thread(target=watch_parent,daemon=True).start()
    def check():
        if ended.is_set():
            root.destroy()
        else:
            root.after(150,check)
    root.after(150,check)
    root.update_idletasks()
    print("ready",flush=True)
    try:
        root.mainloop()
    finally:
        stream.stop()
        stream.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

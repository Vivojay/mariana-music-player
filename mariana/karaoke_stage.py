"""An interactive vocal stage driven directly by the existing media transport."""
from __future__ import annotations

from bisect import bisect_right

from prompt_toolkit.formatted_text.base import OneStyleAndTextTuple
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from .terminal_view import TerminalView
from .theme_palette import resolved_theme


def _clock(ms):
    seconds = ms // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def stage_lines(score, position, part):
    segment = score.segment(position)
    lines = []
    if segment and segment["voices"]:
        for voice in segment["voices"]:
            primary = part is None or part == voice["singer"]
            lines.append(("class:singer" if primary else "class:other", "  " + voice["singer"] + "\n  "))
            for word in voice["words"]:
                active = word["start_ms"] <= position < word["end_ms"]
                color = "class:other" if not primary else "class:active" if active else (
                    "class:past" if word["end_ms"] <= position else "class:future")
                lines.append((color, word["text"]))
                lines.append(("", " "))
            lines.append(("", "\n\n"))
    elif position < score.duration:
        lines.append(("class:singer", "  Instrumental\n\n"))
    else:
        lines.append(("class:singer", "  End of recording\n\n"))
    following = bisect_right(score.sung_starts, position)
    if following < len(score.sung_starts):
        start = score.sung_starts[following]
        voices = score.segment(start)["voices"]
        next_voice = next((voice for voice in voices if voice["singer"] == part), voices[0])
        text = " ".join(word["text"] for word in next_voice["words"])
        lines.append(("class:other", f"  Up next at {_clock(start)} · {next_voice['singer']}\n  {text}"))
    return lines


def sing(session, snapshot, command, appearance, allowed, *, input=None, output=None):
    initial = session.stage(snapshot())
    if not initial["available"]:
        raise ValueError(initial["reason"])
    expected = initial["media_id"]
    view = TerminalView()
    bindings = KeyBindings()
    note = [""]
    def close(event):
        view.finish()
    for key in ("escape", "q", "c-c"):
        bindings.add(key)(close)
    def action(name):
        def handle(event):
            view.finish(name)
        return handle
    for key, name in ((" ", "p"), ("left", "karaoke previous"), ("right", "karaoke next"), ("tab", "part")):
        bindings.add(key)(action(name))

    def render() -> list[OneStyleAndTextTuple]:
        current = snapshot()
        if not allowed() or not current.media or current.media.stable_id != expected:
            view.finish()
            return []
        try:
            score, position = session.active(current)
        except ValueError as error:
            view.finish()
            return [("", str(error))]
        state = str(current.state).capitalize()
        details = f"  {state}   {_clock(position)} / {_clock(score.duration)}   ·   {score.score:.1%}   ·   {session.part or 'All voices'}\n\n"
        return [("class:singer", details), *stage_lines(score, position, session.part)]

    colors = resolved_theme(appearance)["chrome"]
    bg, fg, accent, muted = (colors[n][:7] for n in ("background", "text", "accent", "muted"))
    style = Style.from_dict({"": f"bg:{bg} {fg}", "singer": f"bold {accent}", "active": f"bold bg:{accent} {bg}",
                             "past": muted, "future": fg, "other": muted})
    lyrics = Window(FormattedTextControl(render, focusable=True), wrap_lines=True)
    container = HSplit([
        Window(FormattedTextControl("  Mariana  /  Karaoke"), height=2, style="class:singer"),
        lyrics,
        Window(FormattedTextControl(lambda: note[0] or "  Space  Pause/resume    ← →  Lines    Tab  Singer    Q  Leave"),
               height=2, style="class:other", wrap_lines=True)
    ])
    while allowed():
        try:
            result = view.run(container, focus=lyrics, bindings=bindings, style=style, interval=.08,
                              input=input, output=output)
        except (EOFError, KeyboardInterrupt):
            return
        if result is None or not allowed():
            return
        current = snapshot()
        if not current.media or current.media.stable_id != expected:
            return
        score, _ = session.active(current)
        if result == "part":
            options = [None, *score.singers]
            index = options.index(session.part)
            session.select(current, options[(index + 1) % len(options)] or "all")
        else:
            command(result)

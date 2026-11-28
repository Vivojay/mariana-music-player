"""Shared renderer palettes and validated per-preset user edits."""

import json
import re
from pathlib import Path

PRESETS = json.loads(Path(__file__).with_name("theme_presets.json").read_text(encoding="utf-8"))
COLOR = re.compile(r"#[\da-fA-F]{6}(?:[\da-fA-F]{2})?", re.ASCII)


def active_theme(appearance):
    name = appearance.get("terminal theme")
    return name if isinstance(name, str) and name in PRESETS else "aurora"


def color_keys(name):
    return {f"{group}.{key}".casefold(): f"{group}.{key}"
            for group in ("chrome", "terminal") for key in PRESETS[name][group]}


def saved_colors(appearance, name):
    edits = appearance.get("theme colors")
    values = edits.get(name) if isinstance(edits, dict) else None
    keys = color_keys(name)
    return {keys[key.lower()]: value for key, value in (values.items() if isinstance(values, dict) else ())
            if isinstance(key, str) and key.lower() in keys and isinstance(value, str) and COLOR.fullmatch(value)}


def resolved_theme(appearance):
    name = active_theme(appearance)
    base = PRESETS[name]
    palette = {"name": base["name"], "chrome": dict(base["chrome"]), "terminal": dict(base["terminal"])}
    for key, value in saved_colors(appearance, name).items():
        group, token = key.split(".")
        palette[group][token] = value
    return palette


def change_theme(appearance, args):
    """Return a new settings section without mutating the previously saved state."""
    current = active_theme(appearance)
    if len(args) == 1 and args[0].casefold() in PRESETS:
        return {**appearance, "terminal theme": args[0].casefold()}
    edits = appearance.get("theme colors")
    edits = dict(edits) if isinstance(edits, dict) else {}
    if len(args) == 1 and args[0].casefold() == "reset":
        edits.pop(current, None)
    elif len(args) == 3 and args[0].casefold() == "color":
        key = color_keys(current).get(args[1].casefold())
        if not key or not COLOR.fullmatch(args[2]):
            raise ValueError("Choose a token from 'theme colors' and a #RRGGBB or #RRGGBBAA color")
        edits[current] = {**saved_colors(appearance, current), key: args[2].lower()}
    else:
        raise ValueError("Usage: theme [list|current|PRESET|colors|color TOKEN #RRGGBB|reset]")
    return {**appearance, "theme colors": edits}


def ansi_foreground(color):
    red, green, blue = (int(color[offset:offset + 2], 16) for offset in (1, 3, 5))
    return f"\x1b[38;2;{red};{green};{blue}m"

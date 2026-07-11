"""Compatibility facade over colored 2.x's terminal formatting API."""

from __future__ import annotations

from colored import Back, Fore, Style
from colored.exceptions import InvalidColor


def _value(namespace, name: str) -> str:
    try:
        return str(getattr(namespace, name.lower(), ""))
    except (AttributeError, InvalidColor):
        return ""


def fg(name: str) -> str:
    return _value(Fore, name)


def bg(name: str) -> str:
    return _value(Back, name)


def back(name: str) -> str:
    return bg(name)


def attr(name: str) -> str:
    aliases = {
        "reset": "reset",
        "bold": "bold",
        "dim": "dim",
        "underlined": "underlined",
        "blink": "blink",
        "reverse": "reverse",
        "hidden": "hidden",
    }
    return _value(Style, aliases.get(name.lower(), name))

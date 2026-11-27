"""Keep ordinary ANSI colors in the paired Console's shared output."""
from __future__ import annotations

import re

# The browser supports SGR text presentation only. Drop window commands,
# hyperlinks, device control, cursor movement and incomplete escape sequences.
_CONTROL = re.compile(
    r"(?:\x1b\[|\x9b)(?P<parameters>[0-?]*)(?P<intermediates>[ -/]*)(?P<final>[@-~])"
    r"|(?:\x1b\]|\x9d)(?:[^\x07\x1b\x9c]|\x1b(?!\\))*(?:\x07|\x1b\\|\x9c|$)"
    r"|(?:\x1b[PX^_]|[\x90\x98\x9e\x9f])(?:[^\x1b\x9c]|\x1b(?!\\))*(?:\x1b\\|\x9c|$)"
    r"|(?:\x1b\[|\x9b)[0-?]*[ -/]*$"
    r"|\x1b[ -/]*[0-~]"
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
)
_PARAMETERS = re.compile(r"[0-9;]{0,96}\Z")


def styled_console_output(text: str) -> str:
    """Return the newest text plus bounded SGR codes, with no terminal actions."""
    def replacement(match: re.Match[str]) -> str:
        params = match["parameters"]
        if match["final"] == "m" and not match["intermediates"] and _PARAMETERS.fullmatch(params):
            return f"\x1b[{params}m"
        return ""

    return _CONTROL.sub(replacement, text[-32000:]).replace("\r\n", "\n").replace("\r", "\n")

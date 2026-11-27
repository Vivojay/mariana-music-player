"""Terminal-cell measurements shared by the workspace panels."""

from dataclasses import dataclass

from wcwidth import wcwidth


def cells(value):
    return sum(max(0, wcwidth(ch)) for ch in value)


def clip(value, width):
    if width <= 0:
        return ""
    if cells(value) <= width:
        return value
    used, result = 0, []
    for ch in value:
        step = max(0, wcwidth(ch))
        if used + step >= width:
            break
        result.append(ch)
        used += step
    return "".join(result) + "…"


def wrap(value, width):
    """Wrap at word boundaries, splitting only a token wider than the pane."""
    width = max(2, width)
    lines, line = [], ""
    for word in value.split():
        if line and cells(line) + cells(word) + 1 > width:
            lines.append(line)
            line = ""
        if cells(word) <= width:
            line += (" " if line else "") + word
            continue
        for ch in word:
            if line and cells(line) + max(0, wcwidth(ch)) > width:
                lines.append(line)
                line = ""
            line += ch
    if line:
        lines.append(line)
    return lines


@dataclass(frozen=True, slots=True)
class WorkspaceSize:
    columns: int
    rows: int
    inspector: bool | None = None

    @property
    def side(self):
        if self.columns < 76 or self.rows < 13 or self.inspector is False:
            return 0
        return max(25, min(48, self.columns // 3))

    @property
    def body(self):
        return max(1, self.columns - self.side - bool(self.side))

    @property
    def compact_rows(self):
        if self.side or (self.inspector is False and self.columns >= 76):
            return 0
        if self.inspector:
            return min(9, self.rows // 3, max(0, self.rows - 7))
        if self.rows < 12:
            return 0
        return 2 if self.rows >= 15 else 1

    @property
    def nav_rows(self):
        return 2 if 33 <= self.columns < 75 and self.rows >= 15 else 1

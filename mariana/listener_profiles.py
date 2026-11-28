"""Choose a listener's data directory before starting any playback services."""
from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

DEFAULT = "default"
HELP = 'profile list | current | create NAME | use NAME | rename "OLD NAME" "NEW NAME"'


def _name(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[\w][\w .-]{0,39}", value) or not value[-1].isalnum():
        raise ValueError("Use a profile name of 1–40 letters, numbers, spaces, dashes or underscores ending in a letter or number.")
    return value


class ListenerProfiles:
    def __init__(self, root: Path):
        self.root = root
        self.registry = root / "listener-profiles.sqlite3"

    @contextmanager
    def _db(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.registry, timeout=5)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS listeners (id TEXT PRIMARY KEY, name TEXT NOT NULL, lookup TEXT NOT NULL UNIQUE)")
            db.execute("CREATE TABLE IF NOT EXISTS selection (slot INTEGER PRIMARY KEY CHECK(slot=1), id TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO listeners VALUES ('default','Default','default')")
            db.execute("INSERT OR IGNORE INTO selection VALUES (1,'default')")
            yield db

    def resolve(self, requested=None):
        if not self.registry.exists() and (requested is None or requested.casefold() == DEFAULT):
            return DEFAULT
        with self._db() as db:
            if requested is None:
                row = db.execute("SELECT listeners.id FROM listeners JOIN selection ON listeners.id=selection.id").fetchone()
            else:
                row = db.execute("SELECT id FROM listeners WHERE lookup=?", (_name(requested).casefold(),)).fetchone()
        if row is None:
            raise ValueError("Unknown listener profile. Use profile list or profile create NAME.")
        if row[0] != DEFAULT and not re.fullmatch(r"[0-9a-f]{32}", row[0]):
            raise ValueError("Invalid stored listener profile identifier.")
        return row[0]

    def command(self, args, current):
        op, *values = args or ["list"]
        if op == "help":
            return HELP
        with self._db() as db:
            if op in ("list", "current") and not values:
                rows = db.execute("SELECT id, name, id=(SELECT id FROM selection WHERE slot=1) FROM listeners ORDER BY lookup")
                return "\n".join(f"{name}" + (" · this session" if uid == current else "") +
                                 (" · next launch" if selected else "")
                                 for uid, name, selected in rows if op == "list" or uid == current)
            if op in ("create", "use") and values:
                label = _name(" ".join(values))
                if op == "use":
                    selected = db.execute("SELECT id,name FROM listeners WHERE lookup=?", (label.casefold(),)).fetchone()
                    if not selected:
                        raise ValueError("Unknown listener profile. Use profile list or profile create NAME.")
                    db.execute("UPDATE selection SET id=? WHERE slot=1", (selected[0],))
                    return f'{selected[1]} will open on your next launch. Quit and reopen Mariana to switch.'
                try:
                    db.execute("INSERT INTO listeners VALUES (?,?,?)", (uuid.uuid4().hex, label, label.casefold()))
                except sqlite3.IntegrityError:
                    raise ValueError("A profile with this name already exists.") from None
                return f'Created {label}. Run profile use "{label}" to select it.'
            if op == "rename" and len(values) == 2:
                old, new = map(_name, values)
                if old.casefold() == DEFAULT:
                    raise ValueError("Default keeps the original installation name.")
                try:
                    changed = db.execute("UPDATE listeners SET name=?,lookup=? WHERE lookup=?",
                                         (new, new.casefold(), old.casefold())).rowcount
                except sqlite3.IntegrityError:
                    raise ValueError("A profile with this name already exists.") from None
                if not changed:
                    raise ValueError("Unknown listener profile.")
                return f'Renamed {old} to {new}.'
        raise ValueError(HELP)

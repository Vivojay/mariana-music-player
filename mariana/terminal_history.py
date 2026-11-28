"""Local interactive command recall for the current Mariana profile."""

from __future__ import annotations

import re
import sqlite3
import time
from collections import deque
from contextlib import closing

from prompt_toolkit.history import History

from .paths import runtime_paths

_LIMIT = 100
# Persist only known commands with non-sensitive, closed/numeric operands.
# Free text (e.g. account IDs, searches, paths, URLs) remains session-local.
_SAVEABLE = re.compile(
    r"(?:help|p|now\*?|\.next|\.prev|"
    r"(?:queue|eq|dj|speech|karaoke|tone|theme|accounts|fx|clip|avsync) (?:help|status|list)|"
    r"tone procedure (?:list|play twinkle(?: --(?:bpm|level|chorus) \d{1,3})*)|"
    r"video (?:open|close|status)|play current(?: --(?:audio|video|auto))?|"
    r"seek [-+]?(?:\d{1,6}(?:\.\d{1,3})?[smh%]?|\d{1,2}:\d{2}(?::\d{2})?)|"
    r"tone (?:sine|square|triangle|sawtooth) \d{1,5}(?:\.\d{1,3})?(?: --seconds \d{1,3}(?:\.\d{1,3})?)?)",
    re.IGNORECASE | re.ASCII,
)


class SessionHistory(History):
    """Bounded, ephemeral recall with an optional shared store for safe commands."""

    def __init__(self, path=None):
        super().__init__()
        self.path = path if path is not None else runtime_paths().state("terminal", "history.sqlite3")
        self._entries = deque(maxlen=_LIMIT)
        self.error = ""

    def _connect(self, *, create=False):
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        uri = self.path.resolve().as_uri() + ("?mode=rwc" if create else "?mode=rw")
        return sqlite3.connect(uri, uri=True, timeout=.25)

    def _saved(self):
        if not self.path.is_file():
            return False, []
        try:
            with closing(self._connect()) as db:
                enabled = db.execute("SELECT enabled FROM preference WHERE id=1").fetchone()
                if not enabled or not enabled[0]:
                    return False, []
                rows = db.execute("SELECT entered, line FROM recent ORDER BY entered DESC LIMIT ?", (_LIMIT,))
                return True, list(rows)[::-1]
        except (sqlite3.Error, OSError):
            self.error = "Saved history is unavailable."
            return False, []

    @property
    def saving(self):
        return self._saved()[0]

    def set_saving(self, enabled):
        self.error = ""
        try:
            with closing(self._connect(create=True)) as db, db:
                db.execute("CREATE TABLE IF NOT EXISTS preference (id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS recent (line TEXT PRIMARY KEY, entered INTEGER NOT NULL)")
                db.execute("INSERT OR REPLACE INTO preference VALUES (1, ?)", (int(bool(enabled)),))
                if not enabled:
                    db.execute("DELETE FROM recent")
            return True
        except (sqlite3.Error, OSError):
            self.error = "Could not change saved history."
            return False

    def clear(self):
        self._entries.clear()
        if self.path.is_file():
            try:
                with closing(self._connect()) as db, db:
                    db.execute("DELETE FROM recent")
            except (sqlite3.Error, OSError):
                self.error = "Could not clear saved history."
                return False
        return True

    def append_string(self, string):
        if not string.strip() or len(string) > 4096 or not string.isprintable():
            return
        stamp = time.time_ns()
        if self._entries and self._entries[-1][1] == string:
            self._entries.pop()
        self._entries.append((stamp, string))
        if not _SAVEABLE.fullmatch(string.strip()) or not self.path.is_file():
            return
        try:
            with closing(self._connect()) as db, db:
                # Check opt-in in the write transaction, including changes by other windows.
                db.execute("INSERT OR REPLACE INTO recent (line, entered) "
                           "SELECT ?, ? WHERE EXISTS (SELECT 1 FROM preference WHERE id=1 AND enabled=1)",
                           (string.strip(), stamp))
                db.execute("DELETE FROM recent WHERE line IN "
                           "(SELECT line FROM recent ORDER BY entered DESC LIMIT -1 OFFSET ?)", (_LIMIT,))
        except (sqlite3.Error, OSError):
            self.error = "Could not save this command."

    def get_strings(self):
        _, saved = self._saved()
        # Each process may submit the same command. Keep its most recent use.
        by_line = {}
        for stamp, text in (*saved, *self._entries):
            by_line[text] = max(stamp, by_line.get(text, 0))
        return sorted(by_line, key=by_line.__getitem__)[-_LIMIT:]

    async def load(self):
        for entry in reversed(self.get_strings()):
            yield entry

    def load_history_strings(self):
        return reversed(self.get_strings())

    def store_string(self, string):
        self.append_string(string)

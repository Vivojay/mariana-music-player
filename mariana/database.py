"""Versioned SQLite persistence for queue, identity, radio, and taste data."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import time
from typing import Any, Iterator


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = APP_DIR / "data" / "mariana.db"
SCHEMA_VERSION = 1


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_items (
    stable_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    original_uri TEXT NOT NULL,
    title TEXT,
    artist TEXT,
    album TEXT,
    duration REAL,
    capabilities_json TEXT NOT NULL,
    resolver_json TEXT NOT NULL,
    provenance TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS queue_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_id TEXT NOT NULL REFERENCES media_items(stable_id),
    position INTEGER NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    added_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    failure_policy TEXT NOT NULL DEFAULT 'skip'
);
CREATE UNIQUE INDEX IF NOT EXISTS queue_position_idx ON queue_items(position);
CREATE TABLE IF NOT EXISTS queue_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    current_id INTEGER,
    repeat_mode TEXT NOT NULL DEFAULT 'off',
    shuffle_seed INTEGER,
    consume_mode INTEGER NOT NULL DEFAULT 0,
    autofill INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
INSERT OR IGNORE INTO queue_state(singleton, updated_at) VALUES (1, 0);
CREATE TABLE IF NOT EXISTS queue_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS named_queues (
    name TEXT PRIMARY KEY,
    items_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS track_identities (
    stable_id TEXT PRIMARY KEY,
    identity_json TEXT NOT NULL,
    fingerprint TEXT,
    fingerprint_duration REAL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS lyrics_cache (
    cache_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    provider TEXT NOT NULL,
    plain_lyrics TEXT,
    synced_lyrics TEXT,
    provider_id TEXT,
    identity_confidence REAL NOT NULL DEFAULT 0,
    retrieved_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS radio_stations (
    station_id TEXT PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    homepage TEXT,
    country TEXT,
    language TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    endpoints_json TEXT NOT NULL,
    favorite INTEGER NOT NULL DEFAULT 0,
    last_healthy_endpoint TEXT,
    last_checked REAL,
    failure_count INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS interaction_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_id TEXT,
    event_type TEXT NOT NULL,
    reward REAL NOT NULL,
    context_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS interactions_stable_idx ON interaction_events(stable_id, created_at);
CREATE TABLE IF NOT EXISTS recommendation_features (
    stable_id TEXT PRIMARY KEY,
    features_json TEXT NOT NULL,
    embedding_json TEXT,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS recommendation_models (
    model_id TEXT PRIMARY KEY,
    model_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    champion INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class MarianaDatabase:
    def __init__(self, path: Path | str = DEFAULT_DATABASE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self.migrate()

    def migrate(self) -> None:
        with self.transaction() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._connection.execute(sql, parameters)

    def fetchall(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._connection.execute(sql, parameters))

    def fetchone(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(sql, parameters).fetchone()

    def set_state(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO app_state(key, value_json, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (key, payload, time.time()),
            )

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.fetchone("SELECT value_json FROM app_state WHERE key = ?", (key,))
        return json.loads(row["value_json"]) if row else default

    def backup(self, destination: Path | str | None = None) -> Path:
        destination = Path(destination or self.path.with_suffix(f".{int(time.time())}.bak"))
        with self._lock:
            self._connection.commit()
            shutil.copy2(self.path, destination)
        return destination

    def migrate_legacy_play_counts(self, path: Path | str) -> dict[str, int]:
        """Import aggregate YAML counters once, preserving the original file and prior state."""
        path = Path(path)
        marker = "legacy_play_counts_migrated"
        if self.get_state(marker, False) or not path.is_file():
            return self.get_state("legacy_play_counts", {})
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        counts = (
            payload.get("default_user_data", {})
            .get("stats", {})
            .get("play_count", {})
        )
        normalized = {
            str(key): max(0, int(value))
            for key, value in counts.items()
            if key != "total" and isinstance(value, (int, float))
        }
        backup = path.with_suffix(path.suffix + ".pre-mariana-0.7.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        self.set_state("legacy_play_counts", normalized)
        self.set_state(marker, True)
        return normalized

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "MarianaDatabase":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

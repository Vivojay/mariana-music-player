"""Versioned SQLite persistence for queue, identity, radio, and taste data."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .paths import runtime_paths

SCHEMA_VERSION = 7


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
    chapters_json TEXT NOT NULL DEFAULT '[]',
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
CREATE TABLE IF NOT EXISTS queue_groups (
    group_id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES queue_groups(group_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'manual',
    sibling_position INTEGER NOT NULL,
    strategy TEXT NOT NULL DEFAULT 'custom',
    shuffle_seed INTEGER,
    priority INTEGER NOT NULL DEFAULT 0,
    atomic_group INTEGER NOT NULL DEFAULT 1,
    source_ref TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS queue_groups_parent_idx
ON queue_groups(parent_id, sibling_position);
CREATE TABLE IF NOT EXISTS playlists (
    playlist_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    description TEXT,
    tree_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS playlist_revisions (
    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id TEXT NOT NULL REFERENCES playlists(playlist_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    tree_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(playlist_id, revision)
);
CREATE INDEX IF NOT EXISTS playlist_revisions_playlist_idx
ON playlist_revisions(playlist_id, revision DESC);
CREATE TABLE IF NOT EXISTS albums (
    album_id TEXT PRIMARY KEY,
    release_mbid TEXT UNIQUE,
    title TEXT NOT NULL,
    album_artist TEXT,
    date TEXT,
    country TEXT,
    disambiguation TEXT,
    album_json TEXT NOT NULL,
    fetched_at REAL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS album_search_results (
    search_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    album_id TEXT NOT NULL REFERENCES albums(album_id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    scope TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(search_id, position)
);
CREATE INDEX IF NOT EXISTS album_search_created_idx
ON album_search_results(created_at DESC);
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
CREATE TABLE IF NOT EXISTS loudness_profiles (
    stable_id TEXT PRIMARY KEY,
    content_signature TEXT,
    album_key TEXT,
    track_gain_db REAL,
    track_peak REAL,
    album_gain_db REAL,
    album_peak REAL,
    target_lufs REAL NOT NULL DEFAULT -18.0,
    algorithm TEXT NOT NULL,
    source TEXT NOT NULL,
    complete_album INTEGER NOT NULL DEFAULT 0,
    scanned_at REAL NOT NULL,
    error_text TEXT
);
CREATE INDEX IF NOT EXISTS loudness_content_idx ON loudness_profiles(content_signature);
CREATE INDEX IF NOT EXISTS loudness_album_idx ON loudness_profiles(album_key);
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
CREATE TABLE IF NOT EXISTS media_preferences (
    stable_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK(state IN ('favorite', 'neutral', 'blocked')),
    updated_at REAL NOT NULL
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
CREATE TABLE IF NOT EXISTS library_roots (
    root_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    path_key TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'library-file',
    available INTEGER NOT NULL DEFAULT 1,
    last_seen REAL,
    last_scan REAL,
    backoff_until REAL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS library_files (
    library_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL REFERENCES library_roots(root_id),
    canonical_path TEXT NOT NULL,
    path_key TEXT UNIQUE NOT NULL,
    file_key TEXT,
    content_signature TEXT,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    extension TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'available',
    missing_since REAL,
    scan_generation TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    embedded_lyrics TEXT,
    fingerprint TEXT,
    fingerprint_duration REAL,
    features_json TEXT NOT NULL DEFAULT '{}',
    probe_version INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS library_files_root_idx ON library_files(root_id, state);
CREATE INDEX IF NOT EXISTS library_files_file_key_idx ON library_files(file_key);
CREATE INDEX IF NOT EXISTS library_files_content_idx ON library_files(content_signature);
CREATE TABLE IF NOT EXISTS library_scan_runs (
    scan_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    discovered INTEGER NOT NULL DEFAULT 0,
    changed INTEGER NOT NULL DEFAULT 0,
    unavailable_roots INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL,
    finished_at REAL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS library_jobs (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id TEXT NOT NULL REFERENCES library_files(library_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_until REAL,
    next_retry REAL NOT NULL DEFAULT 0,
    error_code TEXT,
    error_text TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(library_id, stage)
);
CREATE INDEX IF NOT EXISTS library_jobs_ready_idx
ON library_jobs(stage, status, next_retry, priority);
CREATE TABLE IF NOT EXISTS station_sessions (
    session_id TEXT PRIMARY KEY,
    seed_json TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope IN ('hybrid', 'local', 'online')),
    generation_limit INTEGER,
    state TEXT NOT NULL,
    generated_count INTEGER NOT NULL DEFAULT 0,
    ready_ahead INTEGER NOT NULL DEFAULT 0,
    progress_message TEXT,
    error_code TEXT,
    queue_snapshot_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS station_one_active_idx
ON station_sessions(active) WHERE active = 1;
CREATE TABLE IF NOT EXISTS station_items (
    session_id TEXT NOT NULL REFERENCES station_sessions(session_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    stable_id TEXT NOT NULL,
    media_json TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    played INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    PRIMARY KEY(session_id, position),
    UNIQUE(session_id, stable_id)
);
CREATE INDEX IF NOT EXISTS station_items_ready_idx
ON station_items(session_id, played, position);
"""


class MarianaDatabase:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or runtime_paths().database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        previous_version = self._schema_version()
        backup = None
        if previous_version and previous_version < SCHEMA_VERSION:
            backup = self.backup(self.path.with_suffix(self.path.suffix + f".pre-schema-{SCHEMA_VERSION}.bak"))
        try:
            self.migrate()
        except Exception:
            if backup:
                self._connection.close()
                for suffix in ("-wal", "-shm"):
                    self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)
                shutil.copy2(backup, self.path)
            raise

    def _schema_version(self) -> int:
        try:
            row = self._connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.DatabaseError:
            return 0

    def migrate(self) -> None:
        self._connection.executescript(SCHEMA)
        with self.transaction() as connection:
            root_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(library_roots)").fetchall()
            }
            if "origin" not in root_columns:
                connection.execute(
                    "ALTER TABLE library_roots ADD COLUMN origin TEXT NOT NULL DEFAULT 'library-file'"
                )
            media_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(media_items)").fetchall()
            }
            if "chapters_json" not in media_columns:
                connection.execute(
                    "ALTER TABLE media_items ADD COLUMN chapters_json TEXT NOT NULL DEFAULT '[]'"
                )
            queue_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(queue_items)").fetchall()
            }
            if "group_id" not in queue_columns:
                connection.execute("ALTER TABLE queue_items ADD COLUMN group_id TEXT")
            if "sibling_position" not in queue_columns:
                connection.execute("ALTER TABLE queue_items ADD COLUMN sibling_position INTEGER")
                connection.execute("UPDATE queue_items SET sibling_position=position")
            state_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(queue_state)").fetchall()
            }
            if "root_strategy" not in state_columns:
                connection.execute(
                    "ALTER TABLE queue_state ADD COLUMN root_strategy TEXT NOT NULL DEFAULT 'custom'"
                )
            if "root_seed" not in state_columns:
                connection.execute("ALTER TABLE queue_state ADD COLUMN root_seed INTEGER")
            legacy_playlists = connection.execute(
                "SELECT name,items_json,updated_at FROM named_queues"
            ).fetchall()
            for legacy in legacy_playlists:
                name = str(legacy["name"]).strip()
                if not name:
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO playlists(playlist_id,name,name_key,tree_json,created_at,updated_at) "
                    "VALUES(lower(hex(randomblob(16))),?,?,?,?,?)",
                    (
                        name,
                        name.casefold(),
                        json.dumps({"legacy_items": json.loads(legacy["items_json"])}, ensure_ascii=False),
                        legacy["updated_at"],
                        legacy["updated_at"],
                    ),
                )
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

    def delete_state(self, key: str) -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM app_state WHERE key=?", (key,))

    def backup(self, destination: Path | str | None = None) -> Path:
        destination = Path(destination or self.path.with_suffix(f".{int(time.time())}.bak"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with self._lock:
            self._connection.commit()
            temporary.unlink(missing_ok=True)
            output = sqlite3.connect(temporary)
            try:
                self._connection.backup(output)
                self._verify_backup(output)
            finally:
                output.close()
            os.replace(temporary, destination)
        return destination

    @staticmethod
    def _verify_backup(connection: sqlite3.Connection) -> None:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise sqlite3.DatabaseError("SQLite backup integrity check failed")

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

    def __enter__(self) -> MarianaDatabase:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

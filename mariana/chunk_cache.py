"""Chunk-level media cache + probability-ranked lookahead.

Audio/video bytes are cached in fixed blocks keyed by durable media identity
(stable_id), never by signed URLs. Loop spans are pinned while a loop or
play-region repeats them.
"""

from __future__ import annotations

import hashlib
import threading
import time
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(slots=True)
class ChunkStats:
    blocks: int = 0
    bytes: int = 0
    hits: int = 0
    misses: int = 0
    pinned: int = 0
    limit_bytes: int = 0


class ChunkCache:
    """In-memory block index with pluggable byte store.

    The default store keeps bytes in RAM (bounded); callers may attach a
    file-backed store later without changing the ranking/pinning contract.
    """

    def __init__(self, *, limit_bytes: int = 32 * 1024 * 1024, block_bytes: int = 256 * 1024) -> None:
        self.limit_bytes = max(1 * 1024 * 1024, int(limit_bytes))
        self.block_bytes = max(64 * 1024, int(block_bytes))
        self._lock = threading.RLock()
        self._blocks: OrderedDict[tuple[str, int], tuple[float, bytes]] = OrderedDict()
        self._pinned: set[tuple[str, int]] = set()
        self._bytes = 0
        self._hits = 0
        self._misses = 0

    @staticmethod
    def cache_key(stable_id: str, index: int) -> tuple[str, int]:
        digest = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:32]
        return (digest, int(index))

    def get(self, stable_id: str, index: int) -> bytes | None:
        key = self.cache_key(stable_id, index)
        with self._lock:
            entry = self._blocks.get(key)
            if entry is None:
                self._misses += 1
                return None
            self._hits += 1
            # LRU touch unless pinned (pinned entries stay resident anyway).
            if key not in self._pinned:
                self._blocks.move_to_end(key)
            return entry[1]

    def put(self, stable_id: str, index: int, data: bytes) -> None:
        if not data:
            return
        key = self.cache_key(stable_id, index)
        with self._lock:
            previous = self._blocks.get(key)
            if previous is not None:
                self._bytes -= len(previous[1])
                del self._blocks[key]
            self._blocks[key] = (time.time(), bytes(data))
            self._bytes += len(data)
            self._evict_locked()

    def pin_span(self, stable_id: str, first: int, last: int) -> int:
        """Pin [first, last] block indexes for loop/region playback."""
        count = 0
        with self._lock:
            for index in range(max(0, first), max(0, last) + 1):
                key = self.cache_key(stable_id, index)
                if key not in self._pinned:
                    self._pinned.add(key)
                    count += 1
        return count

    def unpin(self, stable_id: str) -> int:
        prefix = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:32]
        with self._lock:
            before = len(self._pinned)
            self._pinned = {key for key in self._pinned if key[0] != prefix}
            self._evict_locked()
            return before - len(self._pinned)

    def _evict_locked(self) -> None:
        while self._bytes > self.limit_bytes and self._blocks:
            # Evict oldest unpinned entry first.
            for key in list(self._blocks):
                if key not in self._pinned:
                    _, data = self._blocks.pop(key)
                    self._bytes -= len(data)
                    break
            else:
                break

    def stats(self) -> ChunkStats:
        with self._lock:
            return ChunkStats(
                blocks=len(self._blocks),
                bytes=self._bytes,
                hits=self._hits,
                misses=self._misses,
                pinned=len(self._pinned),
                limit_bytes=self.limit_bytes,
            )

    def clear(self) -> int:
        with self._lock:
            count = len(self._blocks)
            self._blocks.clear()
            self._pinned.clear()
            self._bytes = 0
            return count


def warm_first_blocks(
    cache: ChunkCache,
    *,
    stable_id: str,
    source: str,
    headers: dict | None = None,
    blocks: int = 2,
    timeout: float = 10,
) -> int:
    """Fetch the first N blocks (bounded) into the cache; return blocks stored.

    Local paths are read directly; HTTP(S) uses a single Range request per
    block. Never follows redirects beyond urllib defaults; never stores more
    than cache.block_bytes * blocks. Raises RuntimeError/OSError on failure
    without mutating existing blocks.
    """
    stored = 0
    if source.startswith(("http://", "https://")):
        for index in range(max(0, blocks)):
            if cache.get(stable_id, index) is not None:
                stored += 1
                continue
            start = index * cache.block_bytes
            end = start + cache.block_bytes - 1
            request = urllib.request.Request(source, method="GET")
            request.add_header("Range", f"bytes={start}-{end}")
            request.add_header("User-Agent", "Mariana-Prefetch/1")
            for key, value in (headers or {}).items():
                if str(key).casefold() in {"authorization", "cookie"}:
                    continue
                request.add_header(str(key), str(value))
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    data = response.read(cache.block_bytes + 1)
            except Exception as error:
                raise RuntimeError(f"Prefetch fetch failed: {error}") from error
            if not data:
                break
            cache.put(stable_id, index, data[: cache.block_bytes])
            stored += 1
            if len(data) < cache.block_bytes:
                break
        return stored
    # Local file path (plain path, no file:// handling needed beyond strip).
    path = source[7:] if source.startswith("file://") else source
    try:
        with open(path, "rb") as handle:
            for index in range(max(0, blocks)):
                if cache.get(stable_id, index) is not None:
                    stored += 1
                    continue
                handle.seek(index * cache.block_bytes)
                data = handle.read(cache.block_bytes)
                if not data:
                    break
                cache.put(stable_id, index, data)
                stored += 1
    except OSError as error:
        raise RuntimeError(f"Prefetch read failed: {error}") from error
    return stored


@dataclass(frozen=True, slots=True)
class PrefetchCandidate:
    stable_id: str
    label: str
    score: float
    reason: str


def rank_prefetch_candidates(
    *,
    queue_next: list[tuple[str, str]] | None = None,
    autoplay_next: tuple[str, str] | None = None,
    chapter_next: tuple[str, str] | None = None,
    hotspot_labels: list[tuple[str, str, float]] | None = None,
    limit: int = 2,
) -> list[PrefetchCandidate]:
    """Score probable lookaheads without starting any network work.

    Weights: queue-next 1.0, autoplay 0.8, chapter/region-loop 0.6,
    hotspot history 0.4 * weight. Deterministic ordering by score then id.
    """
    scored: dict[str, PrefetchCandidate] = {}

    def add(stable_id: str, label: str, score: float, reason: str) -> None:
        previous = scored.get(stable_id)
        total = score + (previous.score if previous else 0.0)
        scored[stable_id] = PrefetchCandidate(
            stable_id,
            label or previous.label if previous else label,
            round(total, 3),
            reason if previous is None else f"{previous.reason}+{reason}",
        )

    for stable_id, label in queue_next or []:
        add(stable_id, label, 1.0, "queue-next")
    if autoplay_next is not None:
        add(autoplay_next[0], autoplay_next[1], 0.8, "autoplay")
    if chapter_next is not None:
        add(chapter_next[0], chapter_next[1], 0.6, "chapter-loop")
    for stable_id, label, weight in hotspot_labels or []:
        try:
            w = max(0.0, min(1.0, float(weight)))
        except (TypeError, ValueError):
            w = 0.5
        add(stable_id, label, round(0.4 * w, 3), "hotspot")
    ranked = sorted(scored.values(), key=lambda item: (-item.score, item.stable_id))
    return ranked[: max(1, limit)]

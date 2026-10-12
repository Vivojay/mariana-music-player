"""On-device smart suggestion ranker. Local history only, never networked.

Sources (all local, opt-in):
- command usage counts (state/suggest-history.json, capped)
- hotspot labels (recently played media titles)
- exact/prefix/substring match quality

Deterministic; disabled by default until the user opts in.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

HISTORY_LIMIT = 200


class SmartSuggester:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.enabled = False
        self._counts: dict[str, int] = {}
        self._updated: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        self.enabled = bool(raw.get("enabled", False))
        counts = raw.get("counts", {})
        updated = raw.get("updated", {})
        if isinstance(counts, dict):
            for key, value in counts.items():
                if isinstance(key, str) and isinstance(value, int) and 0 < value < 10**6 and len(key) <= 96:
                    self._counts[key.casefold()] = value
        if isinstance(updated, dict):
            for key, value in updated.items():
                if isinstance(key, str) and isinstance(value, (int, float)):
                    self._updated[key.casefold()] = float(value)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            items = sorted(self._counts.items(), key=lambda kv: kv[1], reverse=True)[:HISTORY_LIMIT]
            self._counts = dict(items)
            self.path.write_text(
                json.dumps(
                    {
                        "enabled": self.enabled,
                        "counts": self._counts,
                        "updated": {k: self._updated.get(k, 0.0) for k in self._counts},
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def record(self, canonical: str) -> None:
        if not self.enabled:
            return
        key = canonical.casefold()
        if len(key) > 96 or not key.strip():
            return
        self._counts[key] = min(10**6, self._counts.get(key, 0) + 1)
        self._updated[key] = time.time()
        self._save()

    def set_enabled(self, enabled: bool) -> bool:
        self.enabled = bool(enabled)
        self._save()
        return self.enabled

    def score(self, canonical: str, *, match_rank: int, hotspot_boost: float = 0.0) -> float:
        """Lower is better (added to match rank)."""
        if not self.enabled:
            return float(match_rank)
        uses = self._counts.get(canonical.casefold(), 0)
        recency = self._updated.get(canonical.casefold(), 0.0)
        age_days = max(0.0, (time.time() - recency) / 86400.0) if recency else 365.0
        freshness = max(0.0, 1.0 - age_days / 30.0)
        return round(float(match_rank) - min(0.9, uses * 0.05) - freshness * 0.3 - hotspot_boost, 3)


def hotspot_boost_for(canonical: str, hotspot_labels: list[str]) -> float:
    joined = " ".join(hotspot_labels).casefold()
    if not joined:
        return 0.0
    return 0.2 if canonical.casefold() in joined else 0.0

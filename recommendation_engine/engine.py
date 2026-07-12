"""Explainable online preference ranking with Thompson exploration and MMR diversity."""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource

FEATURE_DIMENSIONS = 256
DEFAULT_REWARDS = {
    "like": 5.0,
    "replay": 3.0,
    "completion": 2.0,
    "manual_queue": 1.0,
    "early_skip": -4.0,
    "dislike": -5.0,
    "failure": 0.0,
    "impression": 0.0,
    "start": 0.0,
    "seek": 0.0,
}


@dataclass(slots=True)
class Candidate:
    media: MediaRef
    tags: list[str] = field(default_factory=list)
    collaborative_score: float = 0.0
    embedding: list[float] | None = None


@dataclass(slots=True)
class Recommendation:
    media: MediaRef
    score: float
    reasons: list[str]


def _feature_index(namespace: str, value: str) -> tuple[int, float]:
    digest = hashlib.blake2b(f"{namespace}:{value.casefold()}".encode(), digest_size=8).digest()
    integer = int.from_bytes(digest, "big")
    return integer % FEATURE_DIMENSIONS, 1.0 if integer & 1 else -1.0


def features(candidate: Candidate) -> list[float]:
    vector = [0.0] * FEATURE_DIMENSIONS
    media = candidate.media
    entries = [("source", media.source.value)]
    if media.artist:
        entries.append(("artist", media.artist))
    if media.album:
        entries.append(("album", media.album))
    entries.extend(("tag", tag) for tag in candidate.tags)
    for namespace, value in entries:
        index, sign = _feature_index(namespace, value)
        vector[index] += sign
    vector[0] += 1.0
    vector[1] += max(-1.0, min(1.0, candidate.collaborative_score))
    if candidate.embedding:
        # Deterministic signed projection keeps the optional CLAP tier compatible
        # with the small CPU ranker without training the frozen encoder.
        for index, value in enumerate(candidate.embedding):
            projected = 2 + (index * 1315423911) % (FEATURE_DIMENSIONS - 2)
            vector[projected] += float(value) * (1.0 if index % 2 else -1.0)
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right, strict=True)) / denominator if denominator else 0.0


class OnlineBayesianRanker:
    def __init__(self, dimensions: int = FEATURE_DIMENSIONS, *, noise_variance: float = 4.0):
        self.dimensions = dimensions
        self.noise_variance = noise_variance
        self.precision = [1.0] * dimensions
        self.evidence = [0.0] * dimensions

    @property
    def mean(self) -> list[float]:
        return [evidence / precision for evidence, precision in zip(self.evidence, self.precision, strict=True)]

    def update(self, vector: list[float], reward: float) -> None:
        for index, value in enumerate(vector):
            self.precision[index] += value * value / self.noise_variance
            self.evidence[index] += value * reward / self.noise_variance

    def score(self, vector: list[float], *, explore: bool, rng: random.Random) -> float:
        values = self.mean
        if explore:
            values = [
                rng.gauss(mean, 1 / math.sqrt(precision))
                for mean, precision in zip(values, self.precision, strict=True)
            ]
        return sum(weight * value for weight, value in zip(values, vector, strict=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": self.dimensions,
            "noise_variance": self.noise_variance,
            "precision": self.precision,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OnlineBayesianRanker:
        model = cls(payload["dimensions"], noise_variance=payload["noise_variance"])
        model.precision = list(payload["precision"])
        model.evidence = list(payload["evidence"])
        return model


class RecommendationEngine:
    def __init__(
        self,
        database: MarianaDatabase,
        *,
        model_directory: Path | str | None = None,
        exploration: float = 0.10,
        mmr_lambda: float = 0.75,
        seed: int | None = None,
    ):
        self.database = database
        self.model_directory = Path(model_directory or database.path.parent / "models")
        self.exploration = min(1.0, max(0.0, exploration))
        self.mmr_lambda = min(1.0, max(0.0, mmr_lambda))
        self.rng = random.Random(seed)
        self.ranker = self._load_champion() or OnlineBayesianRanker()

    def _load_champion(self) -> OnlineBayesianRanker | None:
        row = self.database.fetchone(
            "SELECT model_json FROM recommendation_models WHERE champion=1 ORDER BY created_at DESC LIMIT 1"
        )
        return OnlineBayesianRanker.from_dict(json.loads(row["model_json"])) if row else None

    def store_candidate(self, candidate: Candidate) -> list[float]:
        vector = features(candidate)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO recommendation_features(stable_id, features_json, embedding_json, updated_at) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(stable_id) DO UPDATE SET "
                "features_json=excluded.features_json, embedding_json=excluded.embedding_json, "
                "updated_at=excluded.updated_at",
                (
                    candidate.media.stable_id,
                    json.dumps(vector),
                    json.dumps(candidate.embedding) if candidate.embedding is not None else None,
                    time.time(),
                ),
            )
        return vector

    def record_event(
        self,
        media: MediaRef | None,
        event_type: str,
        *,
        reward: float | None = None,
        context: dict[str, Any] | None = None,
        candidate: Candidate | None = None,
    ) -> float:
        value = DEFAULT_REWARDS.get(event_type, 0.0) if reward is None else float(reward)
        stable_id = media.stable_id if media else None
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO interaction_events(stable_id, event_type, reward, context_json, created_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (stable_id, event_type, value, json.dumps(context or {}, sort_keys=True), time.time()),
            )
        if candidate is not None and value:
            self.ranker.update(self.store_candidate(candidate), value)
        return value

    def candidates_from_history(self) -> list[Candidate]:
        rows = self.database.fetchall(
            "SELECT m.*, f.features_json FROM media_items m "
            "LEFT JOIN recommendation_features f ON f.stable_id=m.stable_id ORDER BY m.updated_at DESC"
        )
        candidates = []
        for row in rows:
            from mariana.models import MediaCapabilities

            media = MediaRef(
                stable_id=row["stable_id"],
                source=MediaSource(row["source"]),
                original_uri=row["original_uri"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
                duration=row["duration"],
                capabilities=MediaCapabilities.from_json(row["capabilities_json"]),
                resolver_data=json.loads(row["resolver_json"]),
                provenance=row["provenance"],
            )
            tags = list((media.resolver_data.get("tags") or {}).values())
            candidates.append(Candidate(media, tags=[str(tag) for tag in tags if tag]))
        return candidates

    def _reasons(self, candidate: Candidate, vector: list[float], recent: list[Candidate]) -> list[str]:
        reasons = []
        if candidate.media.artist:
            reasons.append(f"artist affinity: {candidate.media.artist}")
        if candidate.tags:
            reasons.append("tag affinity: " + ", ".join(candidate.tags[:3]))
        if recent:
            similarity = max(cosine(vector, features(item)) for item in recent)
            if similarity > 0.25:
                reasons.append("fits the current listening session")
        if candidate.collaborative_score > 0:
            reasons.append("optional collaborative evidence")
        if not reasons:
            reasons.append("novel local-library exploration")
        return reasons

    def recommend(
        self,
        candidates: Iterable[Candidate] | None = None,
        *,
        limit: int = 10,
        recent: Iterable[Candidate] = (),
        exclude_ids: set[str] | None = None,
    ) -> list[Recommendation]:
        pool = list(candidates if candidates is not None else self.candidates_from_history())
        recent_items = list(recent)
        excluded = exclude_ids or set()
        vectors = {candidate.media.stable_id: self.store_candidate(candidate) for candidate in pool}
        base_scores = {}
        for candidate in pool:
            explore = self.rng.random() < self.exploration
            base_scores[candidate.media.stable_id] = self.ranker.score(
                vectors[candidate.media.stable_id], explore=explore, rng=self.rng
            )
        selected: list[Candidate] = []
        recommendations = []
        artist_counts: dict[str, int] = {}
        remaining = [candidate for candidate in pool if candidate.media.stable_id not in excluded]
        while remaining and len(selected) < max(0, limit):
            ranked = []
            for candidate in remaining:
                artist = (candidate.media.artist or "").casefold()
                if artist and artist_counts.get(artist, 0) >= 2:
                    continue
                vector = vectors[candidate.media.stable_id]
                diversity_penalty = max(
                    (cosine(vector, vectors[item.media.stable_id]) for item in selected), default=0.0
                )
                mmr = self.mmr_lambda * base_scores[candidate.media.stable_id] - (
                    1 - self.mmr_lambda
                ) * diversity_penalty
                ranked.append((mmr, candidate))
            if not ranked:
                break
            score, chosen = max(ranked, key=lambda item: (item[0], item[1].media.stable_id))
            selected.append(chosen)
            remaining.remove(chosen)
            artist = (chosen.media.artist or "").casefold()
            if artist:
                artist_counts[artist] = artist_counts.get(artist, 0) + 1
            recommendations.append(
                Recommendation(chosen.media, score, self._reasons(chosen, vectors[chosen.media.stable_id], recent_items))
            )
        for result in recommendations:
            self.record_event(result.media, "impression", context={"score": result.score, "reasons": result.reasons})
        return recommendations

    def retrain_if_due(self, *, threshold: int = 50, force: bool = False) -> str | None:
        last_id = int(self.database.get_state("recommender_last_event_id", 0))
        rows = self.database.fetchall(
            "SELECT e.id, e.reward, f.features_json FROM interaction_events e "
            "JOIN recommendation_features f ON f.stable_id=e.stable_id WHERE e.id>? ORDER BY e.id",
            (last_id,),
        )
        weighted = [row for row in rows if row["reward"] != 0]
        if not force and len(weighted) < threshold:
            return None
        model = OnlineBayesianRanker()
        all_rows = self.database.fetchall(
            "SELECT e.id, e.reward, f.features_json FROM interaction_events e "
            "JOIN recommendation_features f ON f.stable_id=e.stable_id WHERE e.reward != 0 ORDER BY e.id"
        )
        for row in all_rows:
            model.update(json.loads(row["features_json"]), row["reward"])
        model_id = f"bayesian-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        payload = json.dumps(model.to_dict(), sort_keys=True)
        self.model_directory.mkdir(parents=True, exist_ok=True)
        temporary = self.model_directory / f".{model_id}.tmp"
        target = self.model_directory / f"{model_id}.json"
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(target)
        with self.database.transaction() as connection:
            connection.execute("UPDATE recommendation_models SET champion=0 WHERE champion=1")
            connection.execute(
                "INSERT INTO recommendation_models(model_id, model_json, metrics_json, champion, created_at) "
                "VALUES(?, ?, ?, 1, ?)",
                (model_id, payload, json.dumps({"events": len(all_rows)}), time.time()),
            )
        latest_id = max((row["id"] for row in rows), default=last_id)
        self.database.set_state("recommender_last_event_id", latest_id)
        self.ranker = model
        return model_id

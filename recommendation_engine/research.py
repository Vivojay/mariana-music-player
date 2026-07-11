"""Promotion gate shared by offline RecBole/Implicit challenger experiments."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metrics:
    ndcg_at_10: float
    diversity: float


def should_promote(champion: Metrics, challenger: Metrics) -> bool:
    if champion.ndcg_at_10 <= 0:
        return challenger.ndcg_at_10 > champion.ndcg_at_10 and challenger.diversity >= champion.diversity * 0.95
    ndcg_gain = (challenger.ndcg_at_10 - champion.ndcg_at_10) / champion.ndcg_at_10
    diversity_regression = (champion.diversity - challenger.diversity) / max(champion.diversity, 1e-12)
    epsilon = 1e-12
    return ndcg_gain + epsilon >= 0.02 and diversity_regression <= 0.05 + epsilon

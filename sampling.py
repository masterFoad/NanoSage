"""Pure branch sampling helpers."""

from __future__ import annotations

import math
import random
from typing import Sequence, TypeVar

T = TypeVar("T")


def softmax_sampling_weights(scores: Sequence[float], temperature: float = 0.25) -> list[float]:
    if not scores:
        return []
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    finite_scores = [float(score) for score in scores if math.isfinite(float(score))]
    if len(finite_scores) != len(scores):
        raise ValueError("scores must be finite")
    max_score = max(finite_scores)
    scaled = [(score - max_score) / temperature for score in finite_scores]
    weights = [math.exp(value) for value in scaled]
    total = sum(weights)
    if total <= 0 or not math.isfinite(total):
        return [1.0 for _ in finite_scores]
    return weights


def weighted_sample_without_replacement(
    items: Sequence[T],
    weights: Sequence[float],
    k: int,
    rng: random.Random | None = None,
) -> list[T]:
    """Efraimidis-Spirakis weighted sampling without replacement."""
    if k <= 0 or not items:
        return []
    if len(items) != len(weights):
        raise ValueError("items and weights must have the same length")
    rng = rng or random.Random()
    keyed: list[tuple[float, int, T]] = []
    for idx, (item, weight) in enumerate(zip(items, weights)):
        w = max(0.0, float(weight))
        if w == 0.0:
            continue
        u = max(rng.random(), 1e-12)
        keyed.append((u ** (1.0 / w), idx, item))
    keyed.sort(key=lambda entry: entry[0], reverse=True)
    return [item for _, _, item in keyed[:k]]


def seed_from_query_id(query_id: str) -> int:
    value = 0
    for char in query_id:
        value = ((value * 131) + ord(char)) & 0xFFFFFFFF
    return value


def choose_frontier_index(
    scores: Sequence[float],
    *,
    window_size: int,
    temperature: float,
    rng: random.Random,
) -> tuple[int, bool, float]:
    """Choose within an already priority-sorted frontier window."""
    if not scores:
        raise ValueError("scores must not be empty")
    if window_size <= 1 or len(scores) == 1:
        return 0, False, 0.0
    eligible = list(scores[:window_size])
    weights = softmax_sampling_weights(eligible, temperature=temperature)
    chosen = weighted_sample_without_replacement(list(range(len(eligible))), weights, 1, rng)
    if not chosen:
        return 0, False, 0.0
    index = chosen[0]
    return index, True, weights[index] / sum(weights)


def partition_relative_scores(
    scores: Sequence[float],
    *,
    margin: float,
    absolute_floor: float | None,
    fallback_count: int,
) -> tuple[list[int], float, bool]:
    """Return kept indices, effective cutoff, and whether the all-pruned guard fired."""
    if not scores:
        return [], 0.0, False
    if margin < 0:
        raise ValueError("margin must be non-negative")
    best = max(float(score) for score in scores)
    cutoff = best - margin
    if absolute_floor is not None:
        cutoff = max(cutoff, float(absolute_floor))
    kept = [index for index, score in enumerate(scores) if float(score) >= cutoff]
    if kept:
        return kept, cutoff, False
    count = max(1, int(fallback_count))
    ranked = sorted(range(len(scores)), key=lambda index: (-float(scores[index]), index))
    return ranked[:count], cutoff, True

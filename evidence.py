"""Evidence and branch-selection primitives for NanoSage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Sequence


def stable_id(*parts: object, prefix: str = "ev") -> str:
    material = "\x1f".join(str(part or "") for part in parts)
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


@dataclass(frozen=True)
class EvidenceItem:
    """A downloaded/parsed source snippet with stable provenance."""

    evidence_id: str
    url: str
    file_path: str
    snippet: str = ""
    title: str = ""
    source_engine: str = "unknown"
    content_type: str = ""
    branch_query: str = ""
    confidence: float = 1.0


@dataclass(frozen=True)
class Claim:
    """Atomic claim shell for future claim-ledger/report synthesis work."""

    claim_id: str
    text: str
    evidence_ids: tuple[str, ...] = ()
    confidence: float = 0.0


@dataclass(frozen=True)
class SearchBranch:
    """A candidate branch in the research search frontier."""

    query: str
    depth: int
    relevance: float
    parent_query: str | None = None
    novelty: float = 1.0
    priority: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "priority", branch_priority(self.relevance, self.novelty, self.depth))


def tokenize(text: str) -> set[str]:
    return {token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if token}


def lexical_similarity(left: str, right: str) -> float:
    """Jaccard similarity for cheap query diversity scoring."""
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def novelty_against(query: str, selected_queries: Iterable[str]) -> float:
    similarities = [lexical_similarity(query, selected) for selected in selected_queries]
    if not similarities:
        return 1.0
    return max(0.0, 1.0 - max(similarities))


def branch_priority(relevance: float, novelty: float, depth: int, *, relevance_weight: float = 0.72) -> float:
    """Score branches so relevant, novel, shallower work is explored first."""
    novelty_weight = 1.0 - relevance_weight
    depth_penalty = max(depth - 1, 0) * 0.04
    return (relevance_weight * relevance) + (novelty_weight * novelty) - depth_penalty


def mmr_rerank(candidates: Sequence[tuple[str, float]], *, lambda_relevance: float = 0.72) -> list[tuple[str, float]]:
    """Maximal Marginal Relevance over query candidates.

    Args:
        candidates: `(query, relevance)` pairs. Relevance can be any finite float.
        lambda_relevance: larger values prefer relevance; smaller values prefer diversity.
    """
    if not candidates:
        return []
    if not 0 <= lambda_relevance <= 1:
        raise ValueError("lambda_relevance must be between 0 and 1")

    remaining = list(dict(candidates).items())  # de-duplicate by query, last score wins
    selected: list[tuple[str, float]] = []
    selected_queries: list[str] = []

    while remaining:
        def score(item: tuple[str, float]) -> float:
            query, relevance = item
            diversity_penalty = max((lexical_similarity(query, selected_query) for selected_query in selected_queries), default=0.0)
            return (lambda_relevance * relevance) - ((1.0 - lambda_relevance) * diversity_penalty)

        best = max(remaining, key=score)
        remaining.remove(best)
        selected.append(best)
        selected_queries.append(best[0])
    return selected


def make_evidence_item(page: dict, meta: dict, branch_query: str, snippet: str) -> EvidenceItem:
    url = page.get("url", "")
    file_path = page.get("file_path", "")
    return EvidenceItem(
        evidence_id=stable_id(branch_query, url, file_path, prefix="ev"),
        url=url,
        file_path=file_path,
        snippet=snippet,
        title=meta.get("title", ""),
        source_engine=meta.get("source_engine", "unknown"),
        content_type=meta.get("content_type", ""),
        branch_query=branch_query,
        confidence=1.0 if url and file_path else 0.0,
    )

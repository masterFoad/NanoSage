"""Pure result-selection helpers for scored evidence chunks."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence


def select_scored_results(
    entries: Sequence[dict[str, Any]],
    scores: Sequence[float],
    *,
    top_k: int,
    max_per_document: int = 3,
) -> list[dict[str, Any]]:
    """Return highest-scoring entries with a per-document chunk cap."""
    if top_k <= 0 or not entries:
        return []
    if len(entries) != len(scores):
        raise ValueError("entries and scores must have the same length")
    if max_per_document <= 0:
        return []

    ranked = sorted(
        enumerate(zip(entries, scores)),
        key=lambda item: (-float(item[1][1]), item[0]),
    )
    counts: dict[str, int] = defaultdict(int)
    selected: list[dict[str, Any]] = []
    for _, (entry, score) in ranked:
        metadata = entry.get("metadata", {})
        document_id = str(
            metadata.get("extracted_text_path")
            or metadata.get("file_path")
            or metadata.get("url")
            or metadata.get("parent_evidence_id")
            or metadata.get("evidence_id")
            or "unknown"
        )
        is_chunk = metadata.get("type") == "webchunk" or "chunk_index" in metadata
        if is_chunk and counts[document_id] >= max_per_document:
            continue
        result = dict(entry)
        result["metadata"] = dict(metadata)
        result["metadata"]["search_score"] = float(score)
        selected.append(result)
        if is_chunk:
            counts[document_id] += 1
        if len(selected) >= top_k:
            break
    return selected

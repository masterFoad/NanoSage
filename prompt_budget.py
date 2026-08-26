"""Pure prompt budgeting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class EvidenceTextBlock:
    label: str
    text: str
    score: float = 0.0


def chunk_result_to_block(entry: dict) -> EvidenceTextBlock | None:
    """Format a scored chunk result without falling back to crawler previews."""
    metadata = entry.get("metadata", {})
    text = metadata.get("text", "")
    if not text:
        return None
    evidence_id = metadata.get("parent_evidence_id") or metadata.get("evidence_id", "")
    score = float(metadata.get("search_score", 0.0))
    label = (
        f"Evidence ID: {evidence_id}\n"
        f"URL: {metadata.get('url', '')}\n"
        f"Score: {score:.4f}\n"
        f"Offsets: {metadata.get('char_start', 0)}-{metadata.get('char_end', 0)}\n"
        "Text:"
    )
    return EvidenceTextBlock(label=label, text=text, score=score)


def select_blocks_with_budget(blocks: Iterable[EvidenceTextBlock], char_budget: int) -> list[EvidenceTextBlock]:
    if char_budget <= 0:
        return []
    selected: list[EvidenceTextBlock] = []
    used = 0
    for block in sorted(blocks, key=lambda item: (-item.score, item.label)):
        needed = len(block.label) + len(block.text) + 2
        if used + needed > char_budget:
            break
        selected.append(block)
        used += needed
    return selected


def render_budgeted_prompt(
    stable_prefix: str,
    blocks: Iterable[EvidenceTextBlock],
    char_budget: int,
    *,
    evidence_heading: str,
    suffix: str,
) -> tuple[str, list[EvidenceTextBlock]]:
    """Render a stable instruction prefix followed by whole budgeted blocks."""
    selected = select_blocks_with_budget(blocks, char_budget)
    evidence = "\n\n".join(f"{block.label}\n{block.text}" for block in selected)
    prompt = f"{stable_prefix.rstrip()}\n\n{evidence_heading}\n{evidence}\n\n{suffix.lstrip()}"
    return prompt, selected

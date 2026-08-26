"""Pure prompt budgeting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from typing import Iterable


@dataclass(frozen=True)
class EvidenceTextBlock:
    label: str
    text: str
    score: float = 0.0
    document_id: str = ""
    chunk_index: int = 0


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
    return EvidenceTextBlock(
        label=label,
        text=text,
        score=score,
        document_id=str(evidence_id),
        chunk_index=int(metadata.get("chunk_index", 0) or 0),
    )


def _spread_blocks(blocks: list[EvidenceTextBlock]) -> list[EvidenceTextBlock]:
    """Order one document's chunks so bounded selection spans the document."""
    ordered = sorted(blocks, key=lambda block: (block.chunk_index, block.label))
    if len(ordered) < 3:
        return ordered
    pending = [(0, len(ordered) - 1)]
    indices: list[int] = []
    seen: set[int] = set()
    while pending:
        start, end = pending.pop(0)
        for index in (start, end):
            if index not in seen:
                seen.add(index)
                indices.append(index)
        if end - start > 1:
            middle = (start + end) // 2
            if middle not in seen:
                seen.add(middle)
                indices.append(middle)
            pending.extend(((start, middle), (middle, end)))
    return [ordered[index] for index in indices]


def group_blocks_for_coverage(
    blocks: Iterable[EvidenceTextBlock],
    char_budget: int,
    max_groups: int,
) -> list[list[EvidenceTextBlock]]:
    """Pack whole chunks into bounded calls while spreading coverage.

    Documents are interleaved before calls are packed, and chunks within each
    document are sampled from across its span. This keeps overlapping neighbors
    from consuming every bounded slot before another source or section is read.
    """
    if char_budget <= 0 or max_groups <= 0:
        return []
    by_document: dict[str, list[EvidenceTextBlock]] = defaultdict(list)
    document_order: list[str] = []
    for position, block in enumerate(blocks):
        document_id = block.document_id or f"unlabeled-{position}"
        if document_id not in by_document:
            document_order.append(document_id)
        by_document[document_id].append(block)

    spread = {key: _spread_blocks(by_document[key]) for key in document_order}
    ordered: list[EvidenceTextBlock] = []
    offset = 0
    while True:
        added = False
        for key in document_order:
            if offset < len(spread[key]):
                ordered.append(spread[key][offset])
                added = True
        if not added:
            break
        offset += 1

    groups: list[list[EvidenceTextBlock]] = []
    current: list[EvidenceTextBlock] = []
    used = 0
    for block in ordered:
        needed = len(block.label) + len(block.text) + 2
        if needed > char_budget:
            continue
        if current and used + needed > char_budget:
            groups.append(current)
            if len(groups) >= max_groups:
                return groups
            current = []
            used = 0
        current.append(block)
        used += needed
    if current and len(groups) < max_groups:
        groups.append(current)
    return groups


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

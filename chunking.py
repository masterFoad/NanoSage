"""Pure text normalization and chunking helpers for evidence indexing."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass


_WHITESPACE_RE = re.compile(r"\s+")
_LINE_ENDINGS_RE = re.compile(r"\r\n?")
_HORIZONTAL_WS_RE = re.compile(r"[^\S\n]+")
_WS_BEFORE_NEWLINE_RE = re.compile(r"[^\S\n]+\n")
_WS_AFTER_NEWLINE_RE = re.compile(r"\n[^\S\n]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class EvidenceChunk:
    evidence_id: str
    chunk_index: int
    char_start: int
    char_end: int
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_extracted_text(text: str) -> str:
    """Canonical extraction normalization used by persisted sidecars and spans.

    Horizontal whitespace is collapsed, but single newlines (list items, headings)
    and paragraph breaks are preserved: that structure is what lets the chunker
    split on real boundaries, and it is what a summarizing model reads. Runs of
    blank lines are capped at one so the canonical form stays stable.
    """
    if not text:
        return ""
    normalized = _LINE_ENDINGS_RE.sub("\n", text)
    normalized = _HORIZONTAL_WS_RE.sub(" ", normalized)
    normalized = _WS_BEFORE_NEWLINE_RE.sub("\n", normalized)
    normalized = _WS_AFTER_NEWLINE_RE.sub("\n", normalized)
    normalized = _BLANK_LINES_RE.sub("\n\n", normalized)
    return normalized.strip()


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Find ``quote`` in ``text`` whitespace-insensitively, returning exact offsets.

    Models copy text reliably but cannot count characters, so spans are derived
    here rather than trusted from model output. Matching ignores how whitespace
    is wrapped, but every non-whitespace character must still match in order.
    """
    collapsed_quote = collapse_whitespace(quote)
    if not collapsed_quote:
        return None
    collapsed_text, positions = _collapse_with_positions(text)
    index = collapsed_text.find(collapsed_quote)
    if index == -1:
        return None
    start = positions[index]
    end = positions[index + len(collapsed_quote) - 1] + 1
    return start, end


def _collapse_with_positions(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace while recording each kept character's original index."""
    chars: list[str] = []
    positions: list[int] = []
    pending_space = False
    for index, char in enumerate(text):
        if char.isspace():
            pending_space = bool(chars)
            continue
        if pending_space:
            chars.append(" ")
            positions.append(index)
            pending_space = False
        chars.append(char)
        positions.append(index)
    return "".join(chars), positions


def collapse_whitespace(text: str) -> str:
    """Whitespace-insensitive form used only to compare spans against quotes.

    Canonical text keeps its line structure, but a model echoing a quote back may
    re-wrap it. Comparing both sides in this collapsed form makes span verification
    robust to re-wrapping and to boundary whitespace, without loosening *which*
    characters must match.
    """
    return _WHITESPACE_RE.sub(" ", text or "").strip()


def split_text_into_chunks(
    evidence_id: str,
    text: str,
    *,
    chunk_chars: int = 1200,
    chunk_overlap: int = 200,
    max_chunks_per_doc: int = 40,
) -> list[EvidenceChunk]:
    """Split canonical text into bounded, overlapping evidence chunks.

    Offsets are character indices into the supplied canonical text.
    """
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be non-negative")
    if chunk_overlap >= chunk_chars:
        raise ValueError("chunk_overlap must be smaller than chunk_chars")
    if max_chunks_per_doc <= 0:
        return []

    canonical = text or ""
    chunks: list[EvidenceChunk] = []
    seen_spans: set[tuple[int, int]] = set()
    start = 0
    while start < len(canonical) and len(chunks) < max_chunks_per_doc:
        hard_end = min(len(canonical), start + chunk_chars)
        end = _choose_chunk_end(canonical, start, hard_end, chunk_chars)
        if end <= start:
            end = hard_end
        chunk_text = canonical[start:end].strip()
        char_start = start
        char_end = end
        while chunk_text and canonical[char_start].isspace():
            char_start += 1
        while chunk_text and canonical[char_end - 1].isspace():
            char_end -= 1
        if char_end > char_start and (char_start, char_end) not in seen_spans:
            seen_spans.add((char_start, char_end))
            chunks.append(EvidenceChunk(evidence_id, len(chunks), char_start, char_end, canonical[char_start:char_end]))
        if hard_end >= len(canonical):
            break
        next_start = max(end - chunk_overlap, start + 1)
        if next_start <= start:
            next_start = start + max(1, chunk_chars - chunk_overlap)
        start = next_start
    return chunks


def _choose_chunk_end(text: str, start: int, hard_end: int, chunk_chars: int) -> int:
    if hard_end >= len(text):
        return len(text)
    lower = start + max(chunk_chars // 2, chunk_chars - max(120, chunk_chars // 4))
    lower = min(max(lower, start + 1), hard_end)
    search_region = text[lower:hard_end]
    candidates = []
    for match in re.finditer(r"(?<=[.!?])\s+", search_region):
        candidates.append(lower + match.end())
    for marker in ("\n\n", "\n"):
        idx = text.rfind(marker, lower, hard_end)
        if idx != -1:
            candidates.append(idx + len(marker))
    if candidates:
        return max(candidates)
    space = text.rfind(" ", lower, hard_end)
    if space != -1:
        return space + 1
    return hard_end


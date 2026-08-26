"""Evidence and branch-selection primitives for NanoSage."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping, Sequence

from chunking import locate_quote


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
    extracted_text_path: str = ""
    extracted_text_length: int = 0
    confidence: float = 1.0


@dataclass(frozen=True)
class Claim:
    """Atomic, span-grounded claim proposed by the LLM."""

    claim_id: str
    claim_text: str
    evidence_id: str
    quote: str
    char_start: int
    char_end: int
    confidence: float = 0.0


@dataclass(frozen=True)
class SearchBranch:
    """A candidate branch in the research search frontier."""

    query: str
    depth: int
    relevance: float
    parent_query: str | None = None
    novelty: float = 1.0
    # What to type into a search engine for this branch. `query` is the full
    # research question -- precise for scoring and summarization, but a poor
    # keyword query -- so the two are kept separate.
    search_terms: str = ""
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


def blend_relevance(root_relevance: float, parent_relevance: float | None, parent_weight: float) -> float:
    """Blend similarity-to-root with similarity-to-parent for a child branch.

    Root-only relevance systematically under-scores deeper branches: a question
    about a specific mechanism is further from the root query than a paraphrase
    of the root, so the relative-cutoff pruner discards precisely the specific
    sub-questions a deep search was spawned to answer.
    """
    if not 0.0 <= parent_weight <= 1.0:
        raise ValueError("parent_weight must be between 0 and 1")
    if parent_relevance is None or parent_weight == 0.0:
        return float(root_relevance)
    return ((1.0 - parent_weight) * float(root_relevance)) + (parent_weight * float(parent_relevance))


_LEADING_NUMBER_PATTERN = re.compile(r"^\d+(?:[.,]\d+)*")
# Markdown emphasis and code marks wrap quantities in extracted page text
# ("**3 billion active**"), so they are stripped alongside ordinary punctuation.
_STRIP_CHARS = "([{<\"'“‘$~≈±*_`#.,;:!?)]}>”’"


def _numeric_tokens(text: str) -> list[str]:
    """Quantities in `text`, normalized so 1,024 and 1024 compare equal.

    Only words that *begin* with a digit count. Model names and identifiers carry
    digits that are not quantities -- `OLMoE-1B-7B` is not a claim about 1 and 7,
    and treating it as one rejected a faithful claim whose quote said exactly the
    same thing. A word starting with a letter is an identifier; `3x`, `70B`,
    `2.1`, `16` are quantities.
    """
    numbers = []
    for word in (text or "").split():
        stripped = word.strip(_STRIP_CHARS)
        match = _LEADING_NUMBER_PATTERN.match(stripped)
        if match:
            numbers.append(match.group(0).replace(",", "").rstrip("."))
    return numbers


def numbers_supported_by_quote(claim_text: str, quote: str) -> bool:
    """True when every number in the claim also appears in its quote.

    Span verification proves a quote was copied, not that the claim built on it
    is faithful. Fabricated or drifted figures ("up to 3x in some configs" ->
    "3x faster") are the failure mode that most damages a research report, and
    they are catchable without another model call.
    """
    quote_numbers = set(_numeric_tokens(quote))
    return all(number in quote_numbers for number in _numeric_tokens(claim_text))


def branch_priority(relevance: float, novelty: float, depth: int, *, relevance_weight: float = 0.72) -> float:
    """Score branches so relevant, novel, shallower work is explored first."""
    novelty_weight = 1.0 - relevance_weight
    depth_penalty = max(depth - 1, 0) * 0.04
    return (relevance_weight * relevance) + (novelty_weight * novelty) - depth_penalty


def refresh_search_branch(
    branch: SearchBranch,
    explored_queries: Iterable[str],
    *,
    repush_delta: float = 1e-6,
) -> tuple[SearchBranch, bool]:
    """Recompute novelty and signal when stale priority materially decreased."""
    novelty = novelty_against(branch.query, explored_queries)
    refreshed = SearchBranch(
        query=branch.query,
        depth=branch.depth,
        relevance=branch.relevance,
        parent_query=branch.parent_query,
        novelty=novelty,
        search_terms=branch.search_terms,
    )
    return refreshed, (branch.priority - refreshed.priority) > repush_delta


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


# Em/en dashes terminate a URL: markdown prose runs them straight onto the last
# character ("…/2607.15105—far more than…"), and they are never URL characters.
_URL_PATTERN = re.compile(r"https?://[^\s<>\"'\]\)\u2014\u2013]+")
_URL_TRAILING = ".,;:!?)*\u2014\u2013'\""


def audit_citations(report_text: str, ledger_urls: Iterable[str]) -> dict:
    """Report which URLs a generated report cited, and which are not sources.

    A page's own outbound links live in its extracted text, so a report can cite a
    real, reachable URL that was never fetched or verified. That is a misattribution
    the ledgers cannot otherwise show, so it is measured rather than assumed absent.
    """
    ledger = {url for url in ledger_urls if url}
    cited = {match.group(0).rstrip(_URL_TRAILING) for match in _URL_PATTERN.finditer(report_text or "")}
    inside = sorted(cited & ledger)
    outside = sorted(cited - ledger)
    return {
        "cited_total": len(cited),
        "cited_from_ledger": inside,
        "cited_outside_ledger": outside,
        "ledger_urls_uncited": sorted(ledger - cited),
    }


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
        extracted_text_path=meta.get("extracted_text_path", ""),
        extracted_text_length=int(meta.get("extracted_text_length", 0) or 0),
        confidence=1.0 if url and file_path else 0.0,
    )


def verify_claims(
    claims: Sequence[Claim | Mapping[str, object]],
    canonical_text_by_evidence_id: dict[str, str],
) -> tuple[list[dict], list[dict]]:
    """Verify proposed claims against canonical extracted text spans.

    Returns `(kept, rejected)` serializable ledger entries. Malformed records are
    rejected instead of raising so bad model output can be persisted.
    """
    kept: list[dict] = []
    rejected: list[dict] = []
    for raw_claim in claims:
        claim, reason = _coerce_claim_record(raw_claim)
        if reason:
            rejected.append({"claim": _serializable_claim(raw_claim), "kept": False, "rejection_reason": reason})
            continue
        text = canonical_text_by_evidence_id.get(str(claim["evidence_id"]))
        if text is None:
            rejected.append({"claim": claim, "kept": False, "rejection_reason": "unknown_evidence_id"})
            continue
        # Offsets are DERIVED, never trusted. Models copy text accurately but cannot
        # count characters, so any model-supplied span is treated as advisory only.
        located = locate_quote(text, str(claim["quote"]))
        if located is None:
            rejected.append({"claim": claim, "kept": False, "rejection_reason": "quote_not_found"})
            continue
        if not numbers_supported_by_quote(str(claim["claim_text"]), str(claim["quote"])):
            rejected.append({"claim": claim, "kept": False, "rejection_reason": "numbers_not_in_quote"})
            continue
        start, end = located
        claim["char_start"] = start
        claim["char_end"] = end
        kept.append({"claim": claim, "kept": True})
    return kept, rejected


def _coerce_claim_record(raw_claim: Claim | Mapping[str, object]) -> tuple[dict, str]:
    if isinstance(raw_claim, Claim):
        value = asdict(raw_claim)
    elif isinstance(raw_claim, Mapping):
        value = dict(raw_claim)
    else:
        return _serializable_claim(raw_claim), "malformed_claim"
    required = ("claim_text", "evidence_id", "quote")
    missing = [key for key in required if key not in value]
    if missing:
        return value, "missing_field"
    if not isinstance(value["claim_text"], str) or not isinstance(value["evidence_id"], str) or not isinstance(value["quote"], str):
        return value, "invalid_field_type"
    # Offsets are optional and advisory: verify_claims derives the authoritative
    # span from the quote itself. Reject only values of the wrong type.
    for offset_key in ("char_start", "char_end"):
        supplied = value.get(offset_key, 0)
        if isinstance(supplied, bool) or not isinstance(supplied, int):
            return value, "invalid_field_type"
        value[offset_key] = supplied
    if not value["claim_text"] or not value["evidence_id"] or not value["quote"]:
        return value, "invalid_field_value"
    try:
        confidence = float(value.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return value, "invalid_field_type"
    # Identity comes from the quote, not the offsets: offsets are derived later.
    claim_id = value.get("claim_id") or stable_id(
        value["claim_text"],
        value["evidence_id"],
        value["quote"],
        prefix="cl",
    )
    claim = Claim(
        claim_id=str(claim_id),
        claim_text=value["claim_text"],
        evidence_id=value["evidence_id"],
        quote=value["quote"],
        char_start=value["char_start"],
        char_end=value["char_end"],
        confidence=confidence,
    )
    return asdict(claim), ""


def _serializable_claim(raw_claim: object) -> dict:
    if isinstance(raw_claim, Claim):
        return asdict(raw_claim)
    if isinstance(raw_claim, Mapping):
        return dict(raw_claim)
    return {"raw": repr(raw_claim)}

"""Pure metric computation over NanoSage run artifacts.

Every tuning constant in this repo was calibrated against a single query. These
functions turn the artifacts a run already writes into comparable numbers, so a
config change can be judged across a query set instead of one topic. Nothing here
re-derives a judgement with an LLM: a metric that needs a model to compute is a
metric that drifts when the model does.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping, Sequence

# Metrics where a larger number is the better outcome. Used by `diff_results` so
# a comparison reads as improved/regressed rather than raw deltas the reader has
# to interpret per field.
HIGHER_IS_BETTER = {
    "verified_claims",
    "verified_primitives",
    "verified_evidence",
    "evidence_per_llm_call",
    "claims_per_llm_call",
    "chunk_coverage_ratio",
    "sources_with_claims",
    "sources_with_evidence",
    "source_citation_ratio",
    "report_words",
    "produced_report",
    "coverage_ratio",
}
LOWER_IS_BETTER = {
    "starved_branch_ratio",
    "citations_outside_ledger",
    "max_source_share",
    "claim_rejection_ratio",
    "primitive_rejection_ratio",
    "evidence_rejection_ratio",
    "wall_seconds",
}


def _nodes(toc_tree: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    flat: list[Mapping[str, Any]] = []
    pending = list(toc_tree or [])
    while pending:
        node = pending.pop(0)
        flat.append(node)
        pending[0:0] = list(node.get("children", []))
    return flat


def _ratio(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return numerator / denominator


def compute_run_metrics(
    *,
    toc: Mapping[str, Any] | None = None,
    evidence: Sequence[Mapping[str, Any]] | None = None,
    claims: Mapping[str, Any] | None = None,
    citation_audit: Mapping[str, Any] | None = None,
    dropped_sources: Sequence[Mapping[str, Any]] | None = None,
    coverage: Mapping[str, Any] | None = None,
    report_words: int = 0,
    wall_seconds: float = 0.0,
    produced_report: bool = False,
) -> dict[str, Any]:
    """Reduce one run's artifacts to a flat, comparable metric record.

    Every argument is optional because a failed run writes diagnostics without a
    report, and a partial run must still be measurable -- a harness that cannot
    score failures would report only its successes.
    """
    toc = toc or {}
    evidence = list(evidence or [])
    claims = claims or {}
    citation_audit = citation_audit or {}
    dropped_sources = list(dropped_sources or [])

    nodes = _nodes(toc.get("toc_tree", []))
    kept = list(claims.get("kept", []))
    rejected = list(claims.get("rejected", []))
    selected = [record for record in kept if record.get("selected_for_report")]
    primitive_ledger = claims.get("primitives", {})
    if not isinstance(primitive_ledger, Mapping):
        primitive_ledger = {}
    kept_primitives = list(primitive_ledger.get("kept", []))
    rejected_primitives = list(primitive_ledger.get("rejected", []))
    selected_primitives = [record for record in kept_primitives if record.get("selected_for_report")]

    extraction_calls = sum(int(n.get("metrics", {}).get("claim_extraction_calls", 0) or 0) for n in nodes)
    classification_calls = sum(int(n.get("metrics", {}).get("question_classification_calls", 0) or 0) for n in nodes)
    summary_calls = sum(1 for n in nodes if (n.get("summary") or "").strip())
    llm_calls = extraction_calls + classification_calls + summary_calls
    covered = sum(int(n.get("metrics", {}).get("claim_extraction_chunks_covered", 0) or 0) for n in nodes)
    fetched_chunks = int(toc.get("analytics", {}).get("content_metrics", {}).get("total_corpus_entries", 0) or 0)
    starved = sum(
        1
        for n in nodes
        if (
            int(n.get("metrics", {}).get("verified_claim_count", 0) or 0)
            + int(n.get("metrics", {}).get("verified_primitive_count", 0) or 0)
        ) == 0
    )

    claim_sources = Counter(
        str(record.get("claim", {}).get("source_domain") or record.get("claim", {}).get("evidence_id") or "")
        for record in kept
    )
    selected_sources = Counter(
        str(record.get("claim", {}).get("source_domain") or record.get("claim", {}).get("evidence_id") or "")
        for record in selected
    )
    def _primitive_source_keys(record):
        """Every source a primitive draws on, matching runtime quota accounting.

        Counting only the primary source undercounts how many documents the
        report actually leans on, so a multi-span primitive looked like
        single-source evidence in the metrics while consuming two quotas.
        """
        primitive = record.get("primitive", {}) or {}
        keys = [str(primitive.get("source_domain") or primitive.get("evidence_id") or "")]
        for span in primitive.get("additional_evidence", []) or []:
            if isinstance(span, dict):
                key = str(span.get("source_domain") or span.get("evidence_id") or "")
                if key and key not in keys:
                    keys.append(key)
        return keys

    primitive_sources = Counter(
        key for record in kept_primitives for key in _primitive_source_keys(record)
    )
    selected_primitive_sources = Counter(
        key for record in selected_primitives for key in _primitive_source_keys(record)
    )
    evidence_sources = claim_sources + primitive_sources
    selected_evidence_sources = selected_sources + selected_primitive_sources
    cited = list(citation_audit.get("cited_from_ledger", []))

    metrics: dict[str, Any] = {
        "produced_report": 1 if produced_report else 0,
        "branches": len(nodes),
        "starved_branches": starved,
        "starved_branch_ratio": round(_ratio(starved, len(nodes)), 4),
        "sources_fetched": len(evidence),
        "sources_dropped": len(dropped_sources),
        "sources_with_claims": len([key for key in claim_sources if key]),
        "sources_with_evidence": len([key for key in evidence_sources if key]),
        "source_citation_ratio": round(_ratio(len(cited), len(evidence)), 4),
        "chunks_fetched": fetched_chunks,
        "chunks_covered": covered,
        "chunk_coverage_ratio": round(_ratio(covered, fetched_chunks), 4),
        "verified_claims": len(kept),
        "rejected_claims": len(rejected),
        "verified_primitives": len(kept_primitives),
        "rejected_primitives": len(rejected_primitives),
        "verified_evidence": len(kept) + len(kept_primitives),
        "claim_rejection_ratio": round(_ratio(len(rejected), len(kept) + len(rejected)), 4),
        "primitive_rejection_ratio": round(
            _ratio(len(rejected_primitives), len(kept_primitives) + len(rejected_primitives)), 4
        ),
        "evidence_rejection_ratio": round(
            _ratio(
                len(rejected) + len(rejected_primitives),
                len(kept) + len(rejected) + len(kept_primitives) + len(rejected_primitives),
            ),
            4,
        ),
        "claims_selected": len(selected),
        "primitives_selected": len(selected_primitives),
        "evidence_selected": len(selected) + len(selected_primitives),
        "max_source_share": round(
            _ratio(
                max(selected_evidence_sources.values()),
                len(selected) + len(selected_primitives),
            ) if selected_evidence_sources else 0.0,
            4,
        ),
        "llm_calls": llm_calls,
        "question_classification_calls": classification_calls,
        "claims_per_llm_call": round(_ratio(len(kept), llm_calls), 4),
        "evidence_per_llm_call": round(_ratio(len(kept) + len(kept_primitives), llm_calls), 4),
        "citations_outside_ledger": len(citation_audit.get("cited_outside_ledger", [])),
        "report_words": int(report_words),
        "wall_seconds": round(float(wall_seconds), 2),
    }
    question_types = Counter(
        str(n.get("metrics", {}).get("question_answer_shape", "") or "")
        for n in nodes
    )
    for answer_shape in ("factual", "decision_rule", "formula", "comparison", "contested"):
        metrics[f"question_type_{answer_shape}_branches"] = question_types[answer_shape]
    if coverage:
        addressed = list(coverage.get("addressed_aspects", []))
        unaddressed = list(coverage.get("unaddressed_aspects", []))
        total = len(addressed) + len(unaddressed)
        metrics["coverage_ratio"] = round(_ratio(len(addressed), total), 4)
        metrics["unaddressed_aspects"] = len(unaddressed)
    return metrics


def check_must_mention(report_text: str, terms: Sequence[str]) -> dict[str, Any]:
    """Crude recall check: which required terms appear in the report at all.

    Deliberately shallow. A real gold standard would need per-query answer keys
    that go stale faster than the web does; presence of an obviously required
    term catches gross failure without pretending to grade correctness.
    """
    lowered = (report_text or "").lower()
    hits = [term for term in terms if term and term.lower() in lowered]
    missing = [term for term in terms if term and term.lower() not in lowered]
    return {
        "must_mention_total": len(terms),
        "must_mention_hits": len(hits),
        "must_mention_missing": missing,
        "must_mention_ratio": round(_ratio(len(hits), len(terms)), 4),
    }


def aggregate_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Mean and median of every numeric metric, plus counts that matter as sums."""
    numeric_keys: set[str] = set()
    for record in records:
        for key, value in record.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            numeric_keys.add(key)
    aggregate: dict[str, Any] = {"runs": len(records)}
    for key in sorted(numeric_keys):
        values = [float(record[key]) for record in records if isinstance(record.get(key), (int, float))]
        if not values:
            continue
        ordered = sorted(values)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        aggregate[key] = {
            "mean": round(sum(values) / len(values), 4),
            "median": round(median, 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }
    aggregate["reports_produced"] = sum(1 for record in records if record.get("produced_report"))
    return aggregate


def diff_results(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Compare two aggregate results, labelling each change by direction.

    An A/B between two configs should read as a verdict per metric, not as a wall
    of deltas the reader has to know the polarity of.
    """
    rows: dict[str, Any] = {}
    keys = sorted(set(baseline) | set(candidate))
    for key in keys:
        before, after = baseline.get(key), candidate.get(key)
        if not isinstance(before, Mapping) or not isinstance(after, Mapping):
            continue
        before_mean, after_mean = float(before.get("mean", 0.0)), float(after.get("mean", 0.0))
        delta = round(after_mean - before_mean, 4)
        if math.isclose(delta, 0.0, abs_tol=1e-9):
            verdict = "unchanged"
        elif key in HIGHER_IS_BETTER:
            verdict = "improved" if delta > 0 else "regressed"
        elif key in LOWER_IS_BETTER:
            verdict = "improved" if delta < 0 else "regressed"
        else:
            verdict = "changed"
        rows[key] = {"before": before_mean, "after": after_mean, "delta": delta, "verdict": verdict}
    return {
        "metrics": rows,
        "improved": sorted(k for k, v in rows.items() if v["verdict"] == "improved"),
        "regressed": sorted(k for k, v in rows.items() if v["verdict"] == "regressed"),
    }

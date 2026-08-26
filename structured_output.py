"""Pure structured-output parsing helpers."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Sequence


# A research question and the query actually sent to a search engine are two
# different artifacts. A 200-character question is precise for scoring and
# summarization but a terrible engine query: keyword engines match one incidental
# word out of it (a MediaWiki search for "What are the specific physiological
# thresholds..." returns the dictionary entry for "specific"). So the model emits
# both, and each is used where it belongs.
SUBQUERY_SCHEMA = {
    "name": "nanosage_subqueries",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "question": {"type": "string", "minLength": 1},
                        "search_terms": {"type": "string", "minLength": 1},
                    },
                    "required": ["question", "search_terms"],
                },
            }
        },
        "required": ["questions"],
    },
}

# Words that carry no retrieval signal when a question is squeezed into keywords.
_QUESTION_STOPWORDS = frozenset("""
a an and are as at be been between by can could do does during for from has have how
in into is it its may might not of on or particularly that the their there these
this those to under upon was were what when where which who why will with within
would you your specific different various given related regarding concerning
""".split())

MAX_SEARCH_TERMS = 8


def derive_search_terms(question: str, *, max_terms: int = MAX_SEARCH_TERMS) -> str:
    """Squeeze a long research question into a keyword query, deterministically.

    Used when the model did not supply `search_terms` (legacy path, schema
    failure, or a recursively expanded subquery). Order is preserved so the
    phrase still reads naturally to an engine.
    """
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-']*", question or "")
    kept: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        lowered = token.lower()
        if lowered in _QUESTION_STOPWORDS or len(lowered) < 3:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        kept.append(token)
        if len(kept) >= max_terms:
            break
    return " ".join(kept) if kept else " ".join((question or "").split()[:max_terms])


CLAIM_SCHEMA = {
    "name": "nanosage_claims",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "claim_text": {"type": "string", "minLength": 1},
                        "evidence_id": {"type": "string", "minLength": 1},
                        "quote": {"type": "string", "minLength": 1},
                    },
                    "required": ["claim_text", "evidence_id", "quote"],
                },
            }
        },
        "required": ["claims"],
    },
}


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("structured output must be a JSON object")
    return value


def parse_subquery_response(text: str, max_questions: int) -> list[dict[str, str]]:
    """Return `[{"question": ..., "search_terms": ...}]` from a schema response."""
    value = parse_json_object(text)
    if set(value) != {"questions"}:
        raise ValueError("subquery response contains unexpected fields")
    questions = value.get("questions")
    if not isinstance(questions, list):
        raise ValueError("questions must be a list")
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in questions:
        if not isinstance(item, dict) or set(item) != {"question", "search_terms"}:
            raise ValueError("questions must contain {question, search_terms} objects")
        if not all(isinstance(item[key], str) for key in ("question", "search_terms")):
            raise ValueError("question fields must be strings")
        question = " ".join(item["question"].split())
        terms = " ".join(item["search_terms"].split())
        if not question or question in seen:
            continue
        seen.add(question)
        output.append({"question": question, "search_terms": terms or derive_search_terms(question)})
        if len(output) >= max_questions:
            break
    if not output:
        raise ValueError("questions must contain at least one non-empty entry")
    return output


def parse_claim_response(text: str) -> list[dict[str, Any]]:
    value = parse_json_object(text)
    if set(value) != {"claims"}:
        raise ValueError("claim response contains unexpected fields")
    claims = value.get("claims")
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    required = {"claim_text", "evidence_id", "quote"}
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("claims must contain objects")
        if set(claim) != required:
            raise ValueError("claim object does not match the required schema")
        if not all(isinstance(claim[key], str) and claim[key] for key in required):
            raise ValueError("claim text fields must be non-empty strings")
    return claims


def generate_subqueries_with_fallback(
    llm_manager: Any,
    query: str,
    *,
    count: int,
    fallback: Sequence[str],
    enabled: bool = True,
    log: Callable[[str], None] = print,
) -> list[dict[str, str]]:
    """Request schema-constrained question/search-term pairs, or legacy output.

    The fallback path still returns pairs; search terms are derived locally so
    every downstream caller can rely on the same shape.
    """
    def _from_fallback() -> list[dict[str, str]]:
        return [{"question": item, "search_terms": derive_search_terms(item)} for item in fallback]

    if not enabled:
        log("[INFO] structured_subqueries is disabled; using split_query legacy path.")
        return _from_fallback()
    count = max(1, int(count))
    schema = dict(SUBQUERY_SCHEMA["schema"])
    schema["properties"] = dict(schema["properties"])
    schema["properties"]["questions"] = dict(schema["properties"]["questions"])
    schema["properties"]["questions"].update({"minItems": count, "maxItems": count})
    prompt = (
        "Generate distinct research questions for a recursive web research agent.\n"
        f"Return exactly {count} standalone, specific, non-overlapping questions.\n\n"
        "For each question also give `search_terms`: the query you would type into a "
        "search engine to find sources answering it. Search terms must be a short "
        f"keyword phrase (at most {MAX_SEARCH_TERMS} words), carrying the distinctive "
        "nouns and technical terms. No question words, no punctuation, not a sentence.\n\n"
        f"Research topic:\n{query}"
    )
    try:
        parsed = llm_manager.generate_json_schema(
            prompt,
            SUBQUERY_SCHEMA["name"],
            schema,
            system_message="Return only schema-valid JSON.",
        )
        questions = parse_subquery_response(json.dumps(parsed), count)
        if len(questions) != count:
            raise ValueError(f"expected {count} distinct questions, received {len(questions)}")
        return questions
    except Exception as exc:
        log(f"[WARN] Structured subquery generation unavailable; using split_query fallback: {exc}")
        return _from_fallback()


def build_gap_subquery_prompt(
    branch_question: str,
    branch_summary: str,
    verified_claim_texts: Sequence[str],
    *,
    count: int,
) -> str | None:
    """Build a child-question prompt from what a branch did and did not establish."""
    summary = " ".join((branch_summary or "").split())
    claims = [" ".join(text.split()) for text in verified_claim_texts if text and text.strip()]
    if not summary and not claims:
        return None
    claim_lines = "\n".join(f"- {claim}" for claim in claims) or "- No verified claims."
    return (
        "Generate follow-up research questions that close gaps left by one completed research branch.\n"
        f"Return exactly {max(1, int(count))} standalone, specific, non-overlapping questions. "
        "Target facts, comparisons, mechanisms, constraints, or source evidence that the branch summary "
        "says are missing or that the verified claims do not establish. Do not merely paraphrase the "
        "branch question, summary, or established claims.\n\n"
        "For each question also give `search_terms`: the short query you would type into a search engine. "
        f"Use at most {MAX_SEARCH_TERMS} words, keep distinctive nouns and technical terms, and do not "
        "write a sentence.\n\n"
        f"Branch question:\n{branch_question}\n\n"
        f"Branch evidence summary:\n{summary or 'No branch summary.'}\n\n"
        f"Verified claim texts:\n{claim_lines}"
    )


def generate_gap_subqueries_with_fallback(
    llm_manager: Any,
    branch_question: str,
    branch_summary: str,
    verified_claim_texts: Sequence[str],
    *,
    count: int,
    fallback: Sequence[str],
    enabled: bool = True,
    log: Callable[[str], None] = print,
) -> list[dict[str, str]]:
    """Generate gap-directed children in one schema call, or local fallback."""
    def _from_fallback() -> list[dict[str, str]]:
        return [{"question": item, "search_terms": derive_search_terms(item)} for item in fallback]

    prompt = build_gap_subquery_prompt(
        branch_question,
        branch_summary,
        verified_claim_texts,
        count=count,
    )
    if not enabled or prompt is None:
        return _from_fallback()
    count = max(1, int(count))
    schema = dict(SUBQUERY_SCHEMA["schema"])
    schema["properties"] = dict(schema["properties"])
    schema["properties"]["questions"] = dict(schema["properties"]["questions"])
    schema["properties"]["questions"].update({"minItems": count, "maxItems": count})
    try:
        parsed = llm_manager.generate_json_schema(
            prompt,
            SUBQUERY_SCHEMA["name"],
            schema,
            system_message="Return only schema-valid JSON.",
        )
        questions = parse_subquery_response(json.dumps(parsed), count)
        if len(questions) != count:
            raise ValueError(f"expected {count} distinct questions, received {len(questions)}")
        return questions
    except Exception as exc:
        log(f"[WARN] Gap-driven subquery generation unavailable; using local fallback: {exc}")
        return _from_fallback()


def generate_claims_with_fallback(
    llm_manager: Any,
    branch_query: str,
    evidence_segments: Sequence[str],
    *,
    log: Callable[[str], None] = print,
) -> tuple[list[dict[str, Any]], str | None]:
    """Request span-grounded claims, returning zero claims on structured failure."""
    if not evidence_segments:
        return [], None
    prompt = (
        "Extract concise factual claims from the evidence below.\n"
        "For each claim, copy ONE quote from the evidence character-for-character. The quote must "
        "appear verbatim in the evidence text: do not paraphrase, correct, shorten with ellipses, or "
        "join text across separate evidence segments. Report the evidence_id the quote came from.\n"
        "Claims whose quote cannot be found verbatim in that evidence are discarded, so copying "
        "exactly matters more than covering every point.\n\n"
        f"Branch question: {branch_query}\n\n"
        + "\n\n".join(evidence_segments)
    )
    try:
        parsed = llm_manager.generate_json_schema(
            prompt,
            CLAIM_SCHEMA["name"],
            CLAIM_SCHEMA["schema"],
            system_message="Return only schema-valid JSON.",
        )
        return parse_claim_response(json.dumps(parsed)), None
    except Exception as exc:
        message = str(exc)
        log(f"[WARN] Structured claim extraction unavailable for branch '{branch_query}': {message}")
        return [], message

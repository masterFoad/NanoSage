# NanoSage audit-driven upgrade notes

This branch addresses the first practical slice from the oh-my-review phase-minus-1 audit.

## Audit result

- Run ID: `2026-05-11T184245Z`
- Coverage gate: `PASS_WITH_CAVEATS`
- Main caveat: missing tests/benchmarks and verification scaffolding.

## Issues converted into code changes

1. **Embedding compatibility must be explicit**
   - Retrieval scoring now rejects mismatched query/document embedding dimensions instead of scoring silently or failing opaquely.
   - SigLIP/CLIP sessions now keep query, web text, local text, image, and PDF-page embeddings in the active retriever's own vector space.

2. **Monte Carlo subquery sampling must be bounded**
   - Similarity scores are shifted into non-negative sampling weights.
   - Sampling is without replacement, so selected subqueries cannot duplicate and cannot exceed available candidates.

3. **Output writes must stay inside the configured result root**
   - Added `path_utils.py` containment helpers.
   - Report and TOC writes now resolve through safe output paths.

4. **Provider/model defaults should be operationally upgradeable**
   - Added provider model defaults and environment overrides in `llm_interface.py`.
   - Added `config.example.yaml` so runtime defaults are visible and reproducible.

5. **Async orchestration should not block directly on long LLM calls**
   - Blocking summarization, query enhancement, and final-generation calls inside async flow now run through `asyncio.to_thread`.

6. **Provenance should not drift when downloads are skipped**
   - Web crawler sidecar metadata now matches downloaded pages by URL, not by `zip(ranked, pages)` ordering.

## Remaining follow-up candidates

- Add end-to-end smoke tests with mocked web crawler and mocked LLM manager.
- Decide whether the legacy `web_search.py` path should be deleted, deprecated, or covered with parity tests.
- Add lightweight benchmark fixtures for retrieval latency and recursive traversal depth.
- Extend the new evidence ledger into a full claim ledger with contradiction mining.

## Evidence-guided search branch

The follow-up `upgrade/evidence-guided-search` branch adds the first algorithmic
slice on top of this audit response:

- `EvidenceItem` / `Claim` shells for source-grounded synthesis.
- MMR-style query diversity reranking.
- Priority-queue branch exploration scored by relevance, novelty, and depth.
- `evidence_ledger.json` persistence alongside TOC/report artifacts.

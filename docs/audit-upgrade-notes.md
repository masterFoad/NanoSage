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
- Add lightweight benchmark fixtures for retrieval latency and recursive traversal depth.
- Extend the new evidence ledger into a full claim ledger with contradiction mining.

## Evidence-guided search branch

The follow-up `upgrade/evidence-guided-search` branch adds the first algorithmic
slice on top of this audit response:

- `EvidenceItem` / `Claim` shells for source-grounded synthesis.
- MMR-style query diversity reranking.
- Priority-queue branch exploration scored by relevance, novelty, and depth.
- `evidence_ledger.json` persistence alongside TOC/report artifacts.

## Evidence-path and frontier cleanup

This branch fixes the gap between retrieval and report generation:

- Downloaded pages now get a canonical UTF-8 `<download>.extracted.txt` sidecar. It is whitespace-normalized once at extraction time, and sidecar JSON records the canonical path and length.
- Web evidence is embedded as overlapping canonical-text chunks rather than a single `raw_text[:2048]` vector. Chunk metadata carries the parent evidence id, URL, chunk index, and character offsets into the persisted text.
- Branch summaries retrieve the top scored chunks gathered for that branch and build prompts from labeled chunk text, with a whole-chunk character budget. The final report prompt now has stable instructions first and budgeted variable evidence last.
- Structured subquery generation asks the configured LLM manager for schema-constrained research questions. If the provider rejects `response_format`, returns invalid JSON, or fails validation, NanoSage logs the fallback and uses the legacy `split_query()` behavior.
- `Claim` is now span-grounded. Proposed branch claims are schema-constrained when available, verified in pure Python against persisted canonical text, and persisted to `claim_ledger.json` with rejection reasons.
- The standalone random subquery prefilter is removed from the run path. For compatibility, `monte_carlo_search` now enables stochastic selection inside the ranked frontier and `monte_carlo_samples` defines the top-of-heap sampling window; `monte_carlo_samples: 0` selects the heap maximum deterministically. Per-node and analytics fields were renamed from Monte Carlo selection to frontier sampling so no permanently-false legacy field remains.
- Sampling weights are now softmax-based with `branch_temperature`, and weighted sampling without replacement uses Efraimidis-Spirakis keys. Runs use a local seeded RNG; `seed: null` derives the effective seed from the deterministic query id and records it in artifacts.
- Branch pruning now uses `min_relevance_margin: 0.25`, keeping questions within 0.25 of the best score in each expansion. `min_relevance` remains an optional absolute floor but ships as `null`; this avoids applying the old `0.5` sentence-fragment threshold to intentionally diverse research questions. If an explicit floor would prune every branch, NanoSage logs loudly and explores `min_branches_if_all_pruned` top candidates anyway. Pruned candidates and reasons are recorded in `toc_analysis.json`.

Deliberately left open:

- No bandit, UCB, MCTS, or reward-learning branch policy was added; verified claims are only persisted as signal for a later policy.
- Local corpus loading keeps its existing pooled-document representation; this pass changes downloaded web evidence only.
- The async web/retrieval/LLM integration still needs a live smoke run in an environment with the configured retrieval model and provider. The new pure logic is covered without network or `torch`.

## Keyless fetching, search terms, and dead-code cleanup

- **`local_fetch.py` vendored in.** Keyless DuckDuckGo search and hardened page
  fetching, adapted from the standalone `localfetch` tool so NanoSage keeps no path
  dependency and spawns no extra process. `curl_cffi` and `lxml` are optional soft
  imports; without them NanoSage falls back to its existing engines. Registered as
  `LocalFetchEngine`, used as the first tier inside `fetch_one`, and used for
  markdown extraction in `extract_html_text`. Removes the need for a Tavily key.
- **Challenge pages are no longer indexed as evidence.** A blocked fetch raises
  `BlockedError` so the plain-aiohttp fallback cannot quietly download and store the
  interstitial, and `is_challenge_text()` drops any that slip through by another
  path. Before this, a web run produced five "sources" that were all reCAPTCHA pages.
- **Browser escalation is budgeted per run** (`browser_escalation_limit`, default 0)
  rather than per page, so it cannot launch a browser once per fetched URL.
- **Search terms are separate from research questions.** The subquery schema now
  returns `{question, search_terms}`. The question drives scoring, summarization and
  claim extraction; the short keyword phrase is what reaches the engines. Without
  this, a 200-character question sent to a keyword engine matched one incidental
  word (a MediaWiki search returned the dictionary entry for "specific").
  `derive_search_terms()` supplies terms deterministically for legacy and recursive
  paths.
- **Claim spans are derived, not reported.** Models copy text accurately but cannot
  count characters; requiring offsets from the model verified 1 of 6 claims in a live
  run. The model now supplies only the quote and `locate_quote()` computes exact
  offsets. Same live evidence, 6 of 6 verified, with fabricated quotes still rejected.
- **Canonical normalization preserves structure.** Headings and paragraph breaks
  survive so the chunker splits on real boundaries; `collapse_whitespace()` is used
  only for span comparison, so a re-wrapped quote still matches.
- **Local corpus is chunked like web evidence**, and the loader accepts every text
  format the README documents. Previously `.md` was skipped silently and local
  documents reached the prompt as a 100-character snippet.
- **Dead code removed**: `web_search.py` (unused legacy crawler), five unused
  backward-compatibility shims in `llm_interface.py`, `BraveSearchEngine` (never
  registered), a no-op `aiohttp_client_cache` block, and assorted unused imports and
  helpers. Two silent `except` blocks now log instead of swallowing.

Deliberately left open:

- No bandit, UCB, MCTS, or reward-learning branch policy. Verified claims are
  persisted as signal for a future policy; nothing consumes them yet.
- Browser escalation (`nodriver`) is implemented and budgeted but has not been
  exercised against a live JS-rendered page.
- Search-engine coverage is still thin for heavily-bot-protected domains (NCBI
  blocks every request without a browser), so some queries legitimately return no
  evidence and the report says so rather than inventing any.

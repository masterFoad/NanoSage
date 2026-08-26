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

## Keyless scholarly search

- **`scholarly.py`**: OpenAlex + Europe PMC + arXiv, queried concurrently, merged
  round-robin and deduplicated by DOI (falling back to a normalized title). No API
  key and no identifying parameters; the OpenAlex/Crossref "polite pool" is
  deliberately not used because it trades the operator's email for a speedup.
  Registered as `ScholarlyEngine`, ahead of the web engines.
- **Abstracts are evidence.** These APIs return the abstract with the metadata, so
  a result whose publisher page is paywalled or bot-protected still contributes
  citable text. `_pages_from_abstracts()` writes it as minimal HTML into the branch
  directory, so it flows through the same extraction, canonicalization, chunking and
  verification path as a downloaded page rather than becoming a special evidence type.
- **Result scoring now uses term overlap, not substring containment.** `score_result`
  tested `keyword in title`, which can never match a multi-word query phrase, so
  title and body contributed 0.0 to every result and ranking was decided purely by
  `GOOD_DOMAINS`. A tardigrade biology query returned five arXiv condensed-matter and
  astrophysics papers. Scoring is now the fraction of query terms present.

Deliberately left open:

- `GOOD_DOMAINS` still gives arXiv a flat +2.0 regardless of field, so physics
  preprints remain over-represented in biology queries even after the scoring fix.
  Making the domain bonus field-aware (or lowering it relative to term overlap) is a
  tuning decision that wants the eval harness first.
- Reproducibility is still partial: `seed` governs NanoSage's RNG but not LLM
  sampling, so two runs of the same query differ. Worth closing before any A/B work.

## Report survivability and evidence quality

A traced end-to-end run (6 branches, 24 sources, 639 chunks, 25 verified claims)
produced a `final_report.md` containing exactly one line: `Error generating
response: Request timed out.` The findings below all come from that run.

- **Provider failures propagate instead of becoming text.** Every provider caught
  its exception and returned `f"Error generating response: {e}"`. That string was
  the return value of `generate_final_answer`, so it was written to
  `final_report.md` as the report and the process exited 0. The same swallow sat on
  the branch-summary path, where a failure would silently enter the evidence pool
  as a summary. Providers now raise `LLMGenerationError`. Call sites choose:
  branch summaries and branch expansion degrade and record the failure, final
  report generation aborts the run.
- **`save_report` refuses a non-report.** Ledger writing moved to
  `save_diagnostics()`, which `main.py` calls on the failure path — the branch tree,
  evidence and verified claims are the expensive part of a run and stay usable for a
  retry — while `save_report` rejects an empty answer and exits non-zero on failure.
- **`llm.timeout` raised 60s → 900s** in the LiteLLM example. The final prompt asks
  for 3000+ words; that generation measured 281s against a local model, so the
  shipped configuration could not finish a report on any run, deterministically.
- **Branch summaries are question-directed.** The prompt was literally "Please
  summarize the following text succinctly" with the branch question never passed,
  so the highest-weighted evidence in the report prompt was a generic page digest.
  `summarize_text` now takes the question and asks for an answer to it, including
  an explicit "say so if the evidence does not address this".
- **Claim citations carry their URL.** The report prompt emitted
  `Verified Claim [ev_...]` and a separate flat list of reference URLs with no
  mapping between them, so the model was asked to cite and given no way to. The
  source URL now travels on the claim line.
- **Post-fetch source gate, relative to the branch's best page**
  (`source_relevance_margin`, default 0.15, with an optional absolute
  `min_source_relevance` floor and a `min_sources_per_branch` guard). Ranking
  decided what to download; nothing decided what to keep, so a page that ranked on
  domain reputation still cost a summary and a claim-extraction call. A page is now
  judged by its best chunk against the branch question.

  This shipped first as an absolute threshold of 0.5, calibrated against one run
  where on-topic sources measured 0.61-0.71 and off-topic ones 0.37-0.47. On the
  next run it dropped 15 of 24 sources and emptied two branches: the real score
  distribution is a tight cluster (eight of the fifteen scored 0.45-0.499), so a
  fixed cut lands mid-cluster. The margin form mirrors branch pruning, adapts to
  whatever a branch actually found, and cannot empty a branch.
- **Child branches are scored against their parent, not only the root**
  (`parent_relevance_weight`, default 0.4). Root-only relevance systematically
  under-scores depth: in the traced run "the formula for KV-cache memory as a
  function of layers, head count, head dim and context length" was pruned at
  0.356, and the report's own Limitations section then stated that it could not
  compute a context-length threshold because no source gave that formula.
- **Numbers in a claim must appear in its quote.** Span verification proves a quote
  was copied, not that the claim built on it is faithful; "can be faster in some
  configurations" supported a claim of "3x faster". Rejected as
  `numbers_not_in_quote`. Only words that *begin* with a digit count as
  quantities: the first version read `OLMoE-1B-7B` as a claim about 1 and 7 and
  rejected a faithful claim whose quote said exactly the same thing, so model
  names and identifiers are excluded while `3x`, `70B` and `16 GB` still count.
- **Citations are audited against the ledger** (`citation_audit.json`). A page's
  own outbound links live in its extracted text, so a report can cite a real,
  reachable URL that was never fetched or verified -- one run cited four
  `techtactician.com` related-article links this way. The report prompt now names
  the citable set explicitly, and the audit records what was cited from the ledger,
  what was cited from outside it, and which fetched sources went uncited.
- **Local agentic tools require a corpus** (`agentic_tools.require_corpus`, default
  true). With `workspace: "."` and no corpus, a question about GPU inference spent
  eight calls grepping NanoSage's own source and fed the results to the report.
- **New ledgers**: `dropped_sources.json`, and `summary_failures` inside
  `claim_ledger.json`. A dropped page previously looked like a page that was never
  found, and a failed summary looked like a summary.

Deliberately left open:

- No contradiction detection across claims. The traced run kept two claims that
  disagree ("only the always-active parameters need to live in VRAM" vs "MoE
  reduces compute, but all the weights still load"); both are correctly sourced,
  and reconciling them is a synthesis problem, not a verification one.
- The numeric gate is deterministic, not an entailment check. A claim that distorts
  a quote without touching a number still passes.
- Evidence yield still does not feed back into branch priority. `verified_claim_count`
  is recorded per node and never read; in the traced run two of six branches spent
  269 chunks to produce zero claims and were indistinguishable from productive ones.
  This wants the eval harness before a policy.
- Retrieval is dense-only (MiniLM cosine, no lexical lane, no rerank), which is
  weakest exactly where research queries turn on exact identifiers and figures.

## Claim coverage and gap-driven expansion

- **Claim extraction no longer reuses the summary slice.** Branch summaries keep
  their small relevance-ranked input, while claim extraction reads separate
  whole-chunk batches. Documents are interleaved and chunk positions are spread
  across each document before batching, so overlapping neighbors cannot consume
  every bounded slot before another source or section is read.
- **Claim-extraction cost is explicit.** `claim_extraction_char_budget` defaults
  to 8000 characters per call and `max_claim_extraction_calls_per_branch` defaults
  to 4 calls. `toc_analysis.json` records the calls run and chunks covered for
  each node. A failed batch is recorded with its call index while successful
  batches still reach span verification.
- **Overlapping passes do not duplicate ledger claims.** Proposed claims collapse
  by the same stable `(claim_text, evidence_id, quote)` identity used for
  `claim_id` before verification derives canonical offsets.
- **Recursive expansion now follows evidence gaps.** When a branch has a summary
  or verified claims, one schema-constrained call asks for child questions aimed
  at what those findings failed to establish. This replaces the old enhancement
  plus subquery pair for evidence-bearing branches; branches with neither signal
  retain that legacy fallback.

Deliberately left open:

- Chunk coverage is deterministic document/position diversity, not semantic
  clustering or an embedding-based novelty reranker.
- The configured call ceiling can still leave unread chunks in very large
  branches; the per-node coverage metrics make that tradeoff measurable.
- Gap-directed questions are grounded in summaries and verified claim text, but
  there is no cross-branch contradiction or global knowledge-gap planner.

### Follow-up: gap expansion must degrade to the enhancement path

`generate_gap_subqueries_with_fallback` is called with an empty local fallback, so a
failed or empty gap call returned no questions and the branch expanded to *nothing* --
strictly worse than the `enhance_query` path it replaced. `_generate_branch_expansion`
now falls through to that path when the gap call yields no usable questions.

Measured A/B on the same query, before and after both algorithmic fixes:

| | before | after |
|---|---|---|
| chunks read for claims | 36 of 317 (11%) | 85 of 115 (74%) |
| verified claims | 26 | 44 |
| branches with zero claims | 2 of 6 | 1 of 6 |
| report | 2,653 words | 3,980 words |
| citations outside the ledger | 0 | 0 |

The gap-driven expansion produced, as a child of the peak-VRAM branch, "What is the
per-token KV-cache VRAM growth rate (GB per context token) for a 35B-class MoE model" --
the same quantity an earlier run's report flagged as missing in its own Limitations
section, and which the root-relevance pruner had discarded at 0.356.

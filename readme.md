# Advanced Search Session and Report Generation Pipeline (With Relevance Filtering)

This document describes the algorithm for our multi-modal, **relevance-aware**, recursive search session pipeline. The system enhances a user query, builds a knowledge base from local and web data, recursively explores subqueries (tracking the search hierarchy via a Table of Contents, TOC), **ranks each branch’s relevance** to avoid diving into unrelated topics, and finally generates a detailed report using retrieval-augmented generation (RAG).

## 1. Initialization and Setup

1. **Input Parameters:**

   - User Query (e.g., `"Quantum computing in healthcare"`)
   - Optional parameters (in `main.py`):
     ```
     --corpus_dir
     --device
     --retrieval_model
     --top_k
     --web_search
     --personality
     --rag_model
     --max_depth
     ```
   - YAML Config (e.g. `"results_base_dir"`, `"max_query_length"`, `"web_search_limit"`, `"min_relevance"`)

2. **Configuration Loading:**

   - `load_config(config_path)` (in `main.py`) loads the YAML configuration file.
     - **`"min_relevance"`** is used to determine the cutoff below which subqueries are considered off-topic.

3. **Session Initialization:**
   - A `SearchSession` object is created in `main.py`, passing in the user query, config, etc.
   - Within `SearchSession.__init__()` (in `search_session.py`):
     - A unique `query_id` is generated, and `base_result_dir` is created.
     - The original query is **enhanced** via `chain_of_thought_query_enhancement(query, personality)`.
     - A retrieval model is loaded using `load_retrieval_model(retrieval_model, device)` from `knowledge_base.py`.
     - **`embed_text()`** is used on the **enhanced query** to get a **reference embedding** for relevance checking.
     - If a local corpus directory is provided, documents are loaded with `load_corpus_from_dir()` and added to the knowledge base (`KnowledgeBase.add_documents()`).

## 2. Query Expansion and Recursive Web Search

1. **Subquery Generation:**

   - The **enhanced query** is cleaned with `clean_search_query(query)` and split into smaller subqueries using `split_query(query, max_len)`.

2. **Recursive Web Search with TOC Tracking & Relevance Scoring:**
   - If `web_search_enabled` is true, `SearchSession.run_session()` calls `perform_recursive_web_searches(subqueries, current_depth=1)`.
   - **For each subquery**:
     - A **`TOCNode`** is created to represent this branch, storing:
       - `query_text` (the subquery)
       - `depth` (current recursion level)
       - **`relevance_score`**: computed by comparing the subquery’s embedding to the **enhanced query embedding** via `late_interaction_score()`.
         - If `relevance_score < min_relevance`, the branch is skipped (no web search or deeper subqueries).
       - If above the relevance threshold:
         - A sanitized directory is created (e.g. `web_<subquery>`) via `sanitize_filename()`.
         - **Web results** are downloaded (`download_webpages_ddg()`), parsed (`parse_html_to_text()`), and embedded.
         - **Branch Summaries** are generated with `summarize_text()`.
         - If `current_depth < max_depth`, the system can generate **additional subqueries** (via `chain_of_thought_query_enhancement()`) and recurse further.
   - This process produces a hierarchical **TOC** structure of relevant branches and their summaries.

## 3. Local Retrieval and Summarization

1. **Aggregating the Knowledge Base:**
   - All downloaded web entries plus any local documents are merged into the knowledge base.
2. **Local Retrieval:**
   - `KnowledgeBase.search(enhanced_query, top_k)` finds the most relevant documents (via `retrieve()`).
3. **Summarization:**
   - Both **web results** and **local results** are summarized with `summarize_text()`.
   - The final aggregated data is then used to generate a **detailed report**.

## 4. Retrieval-Augmented Generation (RAG) and Report Generation

1. **Aggregation Prompt Construction:**

   - A final prompt is built in `_build_final_answer()`, including:
     - The **enhanced query**.
     - **A Table of Contents string** built from the TOC nodes (`build_toc_string(toc_tree)`) showing each subquery, depth, and short summary.
     - Summaries of web and local findings.
   - The prompt instructs the system to produce a **long**, multi-section, properly cited Markdown report.

2. **Final Answer Generation:**

   - `rag_final_answer(aggregation_prompt, rag_model, personality)` calls `call_gemma()` to produce a **comprehensive** advanced report.

3. **Report Saving:**
   - The final answer, along with all aggregated data, is saved in a Markdown file via `aggregate_results(...)` (in `aggregator.py`), under the `results_base_dir/<query_id>/` folder.

## 5. Balancing Exploration and Exploitation

By **comparing each subquery’s embedding** to the main query embedding, we:

- **Explore** new subtopics that pass the minimum relevance threshold (`relevance_score >= min_relevance`).
- **Skip** potential rabbit holes if a subquery’s relevance falls below the threshold, preventing expansion into off-topic searches.

## 6. Final Output

- The pipeline outputs a **Markdown report** summarizing the relevant subqueries, local documents, and a thoroughly generated final text via RAG. The path to this report is printed by `main.py`.

## Summary Flow Diagram

```
User Query
    │
    ▼
main.py:
    └── load_config(config.yaml)
         └── Create SearchSession(...)
              │
              ├── chain_of_thought_query_enhancement()
              ├── load_retrieval_model()
              ├── embed_text() for reference
              ├── load_corpus_from_dir() → KnowledgeBase.add_documents()
              └── run_session():
                  └── perform_recursive_web_searches():
                      ├── For each subquery:
                      │   ├─ Compute relevance_score = late_interaction_score()
                      │   ├─ if relevance_score < min_relevance: skip
                      │   ├─ else:
                      │   │   ├─ download_webpages_ddg()
                      │   │   ├─ parse_html_to_text(), embed
                      │   │   ├─ summarize_text() → store in TOCNode
                      │   │   └─ if current_depth < max_depth:
                      │   │       └─ recursively expand additional subqueries
                      └── Aggregates web corpus and builds TOC
              │
              ├── KnowledgeBase.search(enhanced_query, top_k)
              ├── Summarize results
              ├── _build_final_answer() constructs prompt
              ├── rag_final_answer() → call_gemma()
              └── aggregate_results() → saves Markdown
```

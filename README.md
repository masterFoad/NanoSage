# NanoSage 🧙: Advanced Recursive Search & Report Generation  

Deep Researchc assistant that runs on your laptop, using tiny models. - all open source!

This document provides a **cleanly structured overview** of your **multi-modal**, **relevance‐aware**, **recursive search session** pipeline. It explains how the system enhances a user query, builds a knowledge base from local and web data, recursively explores subqueries (tracking the search hierarchy via a **Table of Contents**, TOC), **ranks each branch’s relevance** to avoid unrelated topics, and finally **generates a detailed report** using retrieval-augmented generation (RAG).

---

## Quick Start Guide  

### 1. Install Dependencies

1. Ensure **Python 3.8+** is installed.  
2. Install required packages:

```bash
pip install -r requirements.txt
```

3. *(Optional)* For GPU acceleration, install PyTorch with CUDA:

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```
*(Replace `cu118` with your CUDA version.)*

---

### 2. Set Up Ollama & Pull the Gemma Model

1. **Install Ollama**:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```
*(Windows users: see [ollama.com](https://ollama.com) for installer.)*

2. **Pull Gemma 2B** (for RAG-based summaries):

```bash
ollama pull gemma2:2b
```

---

### 3. Run a Simple Search Query

A sample command to run your **search session**:

```bash
python main.py --query "Create a structure bouldering gym workout to push my climbing from v4 to v6" --web_search --max_depth 2 --device cpu --retrieval_model colpali 
               --web_search \
               --max_depth 2 \
               --device cpu \
               --top_k 10 \
               --retrieval_model colpali
```

**Parameters**:
- `--query`: Main search query (natural language).
- `--web_search`: Enables web-based retrieval.
- `--max_depth`: Recursion depth for subqueries (2 levels).
- `--device cpu`: Uses CPU (swap with `cuda` for GPU).
- `--retrieval_model colpali`: Uses **ColPali** for retrieval (try `all-minilm` for lighter model).

---

### 4. Check Results & Report

A **detailed Markdown report** will appear in `results/<query_id>/`.

**Example**:
```
results/
└── 389380e2/
    ├── Quantum_computing_in_healthcare_output.md
    ├── web_Quantum_computing/
    ├── web_results/
    └── local_results/
```

Open the `*_output.md` file (e.g., `Quantum_computing_in_healthcare_output.md`) in a Markdown viewer (VSCode, Obsidian, etc.).

---

### 5. Advanced Options

#### ✅ Using Local Files

If you have local PDFs, text files, or images:

```bash
python main.py --query "AI in finance" \
               --corpus_dir "my_local_data/" \
               --top_k 5 \
               --device cpu
```

Now the system searches **both** local docs and web data (if `--web_search` is enabled).

#### 🔄 RAG with Gemma 2B

```bash
python main.py --query "Climate change impact on economy" \
               --rag_model gemma \
               --personality "scientific"
```

This uses **Gemma 2B** to generate LLM-based summaries and the final report.

---

### 6. Troubleshooting

- **Missing dependencies?** Rerun: `pip install -r requirements.txt`
- **Ollama not found?** Ensure it’s installed (`ollama list` shows `gemma:2b`).
- **Memory issues?** Use `--device cpu`.
- **Too many subqueries?** Lower `--max_depth` to 1.

---

### 7. Next Steps

- **Try different retrieval models** (`--retrieval_model all-minilm`).
- **Tweak recursion** (`--max_depth`).
- **Tune** `config.yaml` for web search limits, `min_relevance`, or Monte Carlo search.

---

## Detailed Design: NanoSage Architecture

### 1. Core Input Parameters

- **User Query**: E.g. `"Quantum computing in healthcare"`.
- **CLI Flags** (in `main.py`):
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
- **YAML Config** (e.g. `config.yaml`):
  - `"results_base_dir"`, `"max_query_length"`, `"web_search_limit"`, `"min_relevance"`, etc.

### 2. Configuration & Session Setup

1. **Configuration**:  
   `load_config(config_path)` to read YAML settings.
   - **`min_relevance`**: cutoff for subquery branching.

2. **Session Initialization**:  
   `SearchSession.__init__()` sets:
   - A unique `query_id` & `base_result_dir`.
   - Enhanced query via `chain_of_thought_query_enhancement()`.
   - Retrieval model loaded with `load_retrieval_model()`.
   - Query embedding for relevance checks (`embed_text()`).
   - Local files (if any) loaded & added to `KnowledgeBase`.

### 3. Recursive Web Search & TOC Tracking

1. **Subquery Generation**:  
   - The enhanced query is split with `split_query()`.
2. **Relevance Filtering**:  
   - For each subquery, compare embeddings with the main query (via `late_interaction_score()`).  
   - If `< min_relevance`, skip to avoid rabbit holes.
3. **TOCNode Creation**:  
   - Each subquery → `TOCNode`, storing the text, summary, relevance, etc.
4. **Web Data**:  
   - If relevant:  
     - `download_webpages_ddg()` to fetch results.  
     - `parse_html_to_text()` and embed them.  
     - Summarize snippets (`summarize_text()`).  
   - If `current_depth < max_depth`, optionally **expand** new sub-subqueries (chain-of-thought on the current subquery).
5. **Hierarchy**:  
   - All subqueries & expansions form a tree of TOC nodes for the final report.

### 4. Local Retrieval & Summaries

1. **Local Documents** + **Downloaded Web Entries** → appended into `KnowledgeBase`.
2. **KnowledgeBase.search(...)** for top-K relevant docs.
3. Summaries:
   - Summarize web results & local retrieval with `summarize_text()`.

### 5. Final RAG Prompt & Report Generation

1. **_build_final_answer(...)**:
   - Constructs a large prompt including:
     - The user query,
     - Table of Contents (with node summaries),
     - Summaries of web & local results,
     - Reference URLs.
   - Asks for a “multi-section advanced markdown report.”
2. **rag_final_answer(...)**:
   - Calls `call_gemma()` (or other LLM) to produce the final text.
3. **aggregate_results(...)**:
   - Saves the final answer plus search data into a `.md` file in `results/<query_id>/`.

### 6. Balancing Exploration vs. Exploitation

- Subqueries with **relevance_score < min_relevance** are skipped.
- Depth-limited recursion ensures not to blow up on too many expansions.
- **Monte Carlo** expansions (optional) can sample random subqueries to avoid missing unexpected gems.

### 7. Final Output

- **Markdown report** summarizing relevant subqueries, local docs, and a final advanced RAG-based discussion.

---

## Summary Flow Diagram

```plaintext
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
                      │   ├─ Compute relevance_score
                      │   ├─ if relevance_score < min_relevance: skip
                      │   ├─ else:
                      │   │   ├─ download_webpages_ddg()
                      │   │   ├─ parse_html_to_text(), embed
                      │   │   ├─ summarize_text() → store in TOCNode
                      │   │   └─ if depth < max_depth:
                      │   │       └─ recursively expand
                      └── Aggregates web corpus, builds TOC
              │
              ├── KnowledgeBase.search(enhanced_query, top_k)
              ├── Summarize results
              ├── _build_final_answer() → prompt
              ├── rag_final_answer() → call_gemma()
              └── aggregate_results() → saves Markdown
```

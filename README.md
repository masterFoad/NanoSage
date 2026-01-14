# 🧙‍♂️ NanoSage: Advanced Recursive Search & Report Generation  

Deep Research assistant that runs on your laptop, using tiny models. - all open source!

## How is NanoSage different than other Assistant Researchers?

It offers a structured breakdown of a multi-source, relevance-driven, recursive search pipeline. It walks through how the system refines a user query, builds a knowledge base from local and web data, and dynamically explores subqueries—tracking progress through a Table of Contents (TOC).

With Monte Carlo-based exploration, the system balances depth vs. breadth, ranking each branch's relevance to ensure precision and avoid unrelated tangents. The result? A detailed, well-organized report generated using retrieval-augmented generation (RAG), integrating the most valuable insights.

I wanted to experiment with new research methods, so I thought, basically, when we research a topic, we randomly explore new ideas as we search, and NanoSage basically does that!
It explores and records its journey, where each (relevant) step is a node... and then sums it up to you in a neat report!
Where the table of content is basically its search graph. 🧙

---

## 📅 Latest Update - October 17, 2025

> **Major System Enhancement**: Tavily Integration & Hybrid Embedding Architecture

- **Tavily Search API Integration**: Replaced unreliable free search engines with Tavily's robust API, enabling access to high-quality academic sources including PubMed, research journals, and scholarly databases
- **Hybrid Embedding System**: Implemented intelligent model selection where SigLIP/CLIP handle vision tasks (images, PDFs) while all-MiniLM processes text content, eliminating dimension mismatches and optimizing performance
- **Enhanced Web Crawler**: Added comprehensive web content extraction with metadata generation, domain grouping, and fallback search engines for maximum reliability and coverage

---

## Example Report

You can find an example report in the following link:  
[example report output for query: "Create a structure bouldering gym workout to push my climbing from v4 to v6"](https://github.com/masterFoad/NanoSage/blob/main/example_report.md)

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

4. Make sure to update pyOpenSSL and cryptography:

```bash
pip install --upgrade pyOpenSSL cryptography
```

---

### 2. Set Up Ollama & Pull the Gemma Model

1. **Install Ollama**:

```bash
curl -fsSL https://ollama.com/install.sh | sh
pip install --upgrade ollama
```
*(Windows users: see [ollama.com](https://ollama.com) for installer.)*

2. **Pull Gemma 2B** (for RAG-based summaries):

```bash
ollama pull gemma2:2b
```

---

### 3. Configure API Keys

```bash
# Copy the example environment file
cp env.example .env

# Edit .env and add your Tavily API key
# Get your free API key at: https://tavily.com/
TAVILY_API_KEY=your_tavily_api_key_here
```

---

### 4. Run Examples

```bash
# Basic web search with SigLIP (vision + text hybrid) - RECOMMENDED
python main.py --query "machine learning algorithms" --retrieval_model siglip --web_search

# Web search with local documents
python main.py --query "quantum computing" --corpus_dir ./my_documents --retrieval_model siglip --web_search

# Fast text-only search
python main.py --query "artificial intelligence" --retrieval_model all-minilm --web_search

# Local documents only (no web search)
python main.py --query "research papers" --corpus_dir ./my_documents --retrieval_model colpali
```

### ✅ Easy UI (No Command Line)

If you prefer a simple UI, use the Streamlit app:

1. **Install dependencies** (one time):
   ```bash
   pip install -r requirements.txt
   ```
2. **Double-click** `start_ui.bat` (Windows) to launch the UI.
3. A browser window will open with the NanoSage UI.

The UI lets you select:
- Query text
- FAISS root folder or a single index/meta pair
- Retrieval model (must match your index embedding model)

**Note for Windows users:** The UI launcher prefers Python 3.10/3.11. If you installed Python 3.13+ (e.g., 3.14) and see `%1 is not a valid Win32 application`, install Python 3.11 and try again. The launcher will skip Python 3.13+ on PATH and fall back automatically if other versions are installed.

**Parameters**:
- `--query`: Main search query (natural language).
- `--web_search`: Enables web-based retrieval via Tavily API.
- `--retrieval_model`: Choose from `siglip` (recommended), `clip`, `colpali`, or `all-minilm`.
- `--device cpu`: Uses CPU (swap with `cuda` for GPU).
- `--max_depth`: Recursion depth for subqueries (default: 1).

---

### 5. Available Models

- **`siglip`**: Vision + text hybrid (recommended for images/PDFs + web content)
- **`clip`**: Vision + text hybrid (alternative to SigLIP)
- **`colpali`**: Advanced text model (good for documents)
- **`all-minilm`**: Fast text model (good for speed)

---

### 6. Supported File Types

- **Text**: `.txt`, `.md`, `.py`, `.json`, `.yaml`, `.csv`
- **PDFs**: Converted to images for vision models, OCR for text models
- **Images**: `.png`, `.jpg`, `.jpeg` (vision models or OCR fallback)

---

### 7. Check Results & Report

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

### 8. Advanced Options

#### ✅ Using Local Files

If you have local PDFs, text files, or images:

```bash
python main.py --query "AI in finance" \
               --corpus_dir "my_local_data/" \
               --top_k 5 \
               --device cpu
```

Now the system searches **both** local docs and web data (if `--web_search` is enabled).

#### ✅ Using a FAISS Index (index.faiss + meta.jsonl)

If you already have FAISS indexes and JSONL metadata (one line per document), you can load them directly:

```bash
pip install faiss-cpu

python main.py --query "contract law precedents" \
               --faiss_index_path "C:\path\to\index.faiss" \
               --faiss_meta_path "C:\path\to\meta.jsonl" \
               --retrieval_model all-minilm
```

Make sure the FAISS index was built with embeddings from the same retrieval model you select (e.g., `all-minilm`). The metadata lines should include `file_path` and optional `snippet` fields for best report output.

If you have many year/court folders, point to a root directory that contains multiple `index.faiss` + `meta.jsonl` pairs and NanoSage will load them all:

```bash
python main.py --query "contract law precedents" \
               --faiss_root_dir "C:\Users\vasil\Desktop\Ai project\_INDEX" \
               --retrieval_model all-minilm
```

#### 🔄 RAG with Gemma 2B

```bash
python main.py --query "Climate change impact on economy" \
               --rag_model gemma \
               --personality "scientific"
```

This uses **Gemma 2B** to generate LLM-based summaries and the final report.

---

### 9. Troubleshooting

- **Missing dependencies?** Rerun: `pip install -r requirements.txt`
- **Ollama not found?** Ensure it's installed (`ollama list` shows `gemma:2b`).
- **Memory issues?** Use `--device cpu`.
- **Too many subqueries?** Lower `--max_depth` to 1.
- **Web search not working?** Check your `TAVILY_API_KEY` in `.env` file.

---

### 10. Next Steps

- **Try different retrieval models** (`--retrieval_model siglip` for best results).
- **Tweak recursion** (`--max_depth`).
- **Tune** `config.yaml` for web search limits, `min_relevance`, or Monte Carlo search.

---

## Hybrid Embedding System

NanoSage uses a **hybrid embedding approach** for optimal performance:

- **Vision Models (SigLIP/CLIP)**: 
  - Use **SigLIP/CLIP** for images and PDFs → images
  - Use **all-MiniLM** for text content (web pages, documents)
  - Ensures consistent 384D embeddings for text content

- **Text Models (ColPali/all-MiniLM)**:
  - Use the same model for all content types
  - Consistent embedding dimensions

This approach eliminates dimension mismatches and uses the right tool for each content type.

## Web Search Integration

- **Primary**: Tavily Search API (reliable, academic sources)
- **Fallback**: DuckDuckGo, SearxNG, Wikipedia
- **Sources**: PubMed, academic journals, research databases
- **Features**: Real-time search, content extraction, metadata generation

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

2. **Monte Carlo Subquery Sampling (Optional)**:  
   - The system can use a **Monte Carlo approach** to intelligently sample the most relevant subqueries, balancing exploration depth with computational efficiency.
   - Each subquery is scored for relevance against the main query using embedding similarity.
   - Only the most promising subqueries are selected for further exploration.

3. **Relevance Filtering**:  
   - For each subquery, compare embeddings with the main query (via `late_interaction_score()`).  
   - If `< min_relevance`, skip to avoid rabbit holes.

4. **TOCNode Creation**:  
   - Each subquery → `TOCNode`, storing the text, summary, relevance, etc.

5. **Web Data**:  
   - If relevant:  
     - `search_and_download()` via Tavily API to fetch results.  
     - `parse_any_to_text()` and embed them.  
     - Summarize snippets (`summarize_text()`).  
   - If `current_depth < max_depth`, optionally **expand** new sub-subqueries (chain-of-thought on the current subquery).

6. **Hierarchy**:  
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
   - Asks for a "multi-section advanced markdown report."

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
                      │   │   ├─ search_and_download() (Tavily API)
                      │   │   ├─ parse_any_to_text(), embed
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

---

If you found **NanoSage** useful for your research or project - or saved you 1 minute of googling, please consider citing it:  

**BibTeX Citation:**  
```bibtex
@misc{NanoSage,
  author = {Foad Abo Dahood}, 
  title = {NanoSage: A Recursive, Relevance-Driven Search and RAG Pipeline},
  year = {2025},
  howpublished = {\url{https://github.com/masterFoad/NanoSage}},
  note = {Accessed: \today}
}
```

**APA Citation:**  
Foad, Abo Dahood. (2025). *NanoSage: A Recursive, Relevance-Driven Search and RAG Pipeline*. Retrieved from [https://github.com/masterFoad/NanoSage](https://github.com/masterFoad/NanoSage)

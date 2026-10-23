# NanoSage — agent guide

NanoSage is a **standalone repository**. Everything needed to work on it lives here.

Do not import, reference, or carry over concepts, terminology, benchmarks, or conventions from
any other project on this machine. If a concept is not defined inside this repo or in the task
brief you were given, it does not apply here.

## What this project is

A local-first recursive research agent: enhance a query, derive subqueries, search the web
(Tavily → DuckDuckGo → SearxNG → Wikipedia; `youcom_search: true` adds an optional keyless
You.com hosted engine, and `SERPLY_API_KEY` adds Serply Google results after Tavily, `SEARCHAPI_API_KEY` adds SearchApi Google results after Serply), download and extract page text, embed it, explore a
scored branch frontier, summarize each branch with an LLM, and emit a Markdown report plus a
TOC/analytics JSON.

## Layout

- `main.py` — CLI entry point and config resolution
- `search_session.py` — orchestration: subqueries, branch frontier, summarization, report prompt
- `knowledge_base.py` — retrieval model loading, embedding, corpus search
- `web_crawler.py` — multi-engine search, downloading, text extraction, sidecar metadata
- `evidence.py` — evidence/claim primitives, MMR reranking, branch priority
- `agent_tools.py` — sandboxed read-only local tools and the agentic policy loop
- `llm_interface.py` — provider abstraction (Ollama / OpenAI / Anthropic / LiteLLM)
- `aggregator.py` — report writing
- `path_utils.py` — output containment helpers
- `tests/` — `unittest` suites

## Conventions

- Python 3.8+, `from __future__ import annotations`, dataclasses, type hints on new code.
- `unittest`, not pytest. Tests must not require network access.
- `print("[INFO] ...")` / `[WARN]` / `[DEBUG]` style logging.
- All output writes go through `path_utils` containment helpers — never write outside the
  configured results root.
- Provider configuration stays generic: endpoints, ports, and model names come from environment
  variables and the example YAMLs. Never hardcode a specific endpoint or model in tracked files.
- `torch` may not be installed in the ambient environment. Prefer pure functions with no torch or
  network dependency for new logic so it stays testable.

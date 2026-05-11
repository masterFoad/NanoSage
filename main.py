# main.py

import argparse
import asyncio
import yaml
import os

from search_session import SearchSession

def load_config(config_path):
    if not os.path.isfile(config_path):
        return {}
    with open(config_path, "r") as f:
        config = yaml.safe_load(f) or {}
    if not isinstance(config, dict):
        raise ValueError(f"Configuration file must contain a YAML mapping: {config_path}")
    return config


def _cfg(config, key, cli_value, default):
    return cli_value if cli_value is not None else config.get(key, default)


def _positive_int(name, value):
    value = int(value)
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value


def _non_negative_int(name, value):
    value = int(value)
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value

def main():
    parser = argparse.ArgumentParser(description="Multi-step RAG pipeline with depth-limited searching.")
    parser.add_argument("--query", type=str, required=True, help="Initial user query")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to YAML configuration file")
    parser.add_argument("--corpus_dir", type=str, default=None, help="Path to local corpus folder")
    parser.add_argument("--device", type=str, default=None, help="Device for retrieval model (cpu or cuda)")
    parser.add_argument("--retrieval_model", type=str, choices=["colpali", "all-minilm", "siglip", "clip"], default=None)
    parser.add_argument("--top_k", type=int, default=None, help="Number of local docs to retrieve")
    parser.add_argument("--web_search", action="store_true", default=None, help="Enable web search")
    parser.add_argument("--personality", type=str, default=None, help="Optional personality for LLM (e.g. cheerful)")
    parser.add_argument("--rag_model", type=str, default=None, help="Which model family to use for final RAG steps")
    parser.add_argument("--max_depth", type=int, default=None, help="Depth limit for subquery expansions")
    parser.add_argument("--llm_provider", type=str, choices=["ollama", "openai", "anthropic"], default=None, help="LLM provider to use")
    parser.add_argument("--llm_model", type=str, default=None, help="Specific LLM model to use (overrides provider default)")
    parser.add_argument("--web_concurrency", type=int, default=None, help="Concurrent web downloads")
    parser.add_argument("--include_wikipedia", action="store_true", default=None, help="Include Wikipedia in web search")
    args = parser.parse_args()

    config = load_config(args.config)
    llm_config = config.get("llm", {})
    if llm_config and not isinstance(llm_config, dict):
        raise ValueError("config key 'llm' must be a mapping")

    device = _cfg(config, "device", args.device, "cpu")
    retrieval_model = _cfg(config, "retrieval_model", args.retrieval_model, "siglip")
    top_k = _positive_int("top_k", _cfg(config, "top_k", args.top_k, 3))
    max_depth = _non_negative_int("max_depth", _cfg(config, "max_depth", args.max_depth, 1))
    web_search_enabled = bool(_cfg(config, "web_search", args.web_search, False))
    web_concurrency = _positive_int("web_concurrency", _cfg(config, "web_concurrency", args.web_concurrency, 8))
    include_wikipedia = bool(_cfg(config, "include_wikipedia", args.include_wikipedia, False))
    llm_provider = _cfg(llm_config, "provider", args.llm_provider, "ollama")
    llm_model = _cfg(llm_config, "model", args.llm_model, None)
    rag_model = _cfg(config, "rag_model", args.rag_model, "gemma")

    # Add web crawler config options
    config.update({
        "web_concurrency": web_concurrency,
        "include_wikipedia": include_wikipedia,
        "web_search": web_search_enabled,
    })

    session = SearchSession(
        query=args.query,
        config=config,
        corpus_dir=args.corpus_dir,
        device=device,
        retrieval_model=retrieval_model,
        top_k=top_k,
        web_search_enabled=web_search_enabled,
        personality=args.personality,
        rag_model=rag_model,
        max_depth=max_depth,
        llm_provider=llm_provider,
        llm_model=llm_model
    )

    final_answer = asyncio.run(session.run_session())

    # Save final report
    output_path = session.save_report(final_answer)
    print(f"[INFO] Final report saved to: {output_path}")


if __name__ == "__main__":
    main()

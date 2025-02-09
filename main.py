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
        return yaml.safe_load(f)

def main():
    parser = argparse.ArgumentParser(description="Multi-step RAG pipeline with depth-limited searching.")
    parser.add_argument("--query", type=str, required=True, help="Initial user query")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to YAML configuration file")
    parser.add_argument("--corpus_dir", type=str, default=None, help="Path to local corpus folder")
    parser.add_argument("--device", type=str, default="cpu", help="Device for retrieval model (cpu or cuda)")
    parser.add_argument("--retrieval_model", type=str, choices=["colpali", "all-minilm"], default="colpali")
    parser.add_argument("--top_k", type=int, default=3, help="Number of local docs to retrieve")
    parser.add_argument("--web_search", action="store_true", default=False, help="Enable web search")
    parser.add_argument("--personality", type=str, default=None, help="Optional personality for Gemma (e.g. cheerful)")
    parser.add_argument("--rag_model", type=str, default="gemma", help="Which model to use for final RAG steps")
    parser.add_argument("--max_depth", type=int, default=1, help="Depth limit for subquery expansions")
    args = parser.parse_args()

    config = load_config(args.config)

    session = SearchSession(
        query=args.query,
        config=config,
        corpus_dir=args.corpus_dir,
        device=args.device,
        retrieval_model=args.retrieval_model,
        top_k=args.top_k,
        web_search_enabled=args.web_search,
        personality=args.personality,
        rag_model=args.rag_model,
        max_depth=args.max_depth
    )

    loop = asyncio.get_event_loop()
    final_answer = loop.run_until_complete(session.run_session())

    # Save final report
    output_path = session.save_report(final_answer)
    print(f"[INFO] Final report saved to: {output_path}")


if __name__ == "__main__":
    main()

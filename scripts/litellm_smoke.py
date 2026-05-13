#!/usr/bin/env python3
"""Credential-safe NanoSage LiteLLM smoke test."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm_interface import create_llm_manager


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a minimal LiteLLM completion smoke test.")
    parser.add_argument("--base-url", default=os.getenv("LITELLM_BASE_URL") or os.getenv("LITELLM_API_BASE") or "http://localhost:4000/v1")
    parser.add_argument("--model", default=os.getenv("NANOSAGE_LITELLM_MODEL") or os.getenv("LITELLM_MODEL") or "gpt-4o-mini")
    parser.add_argument("--prompt", default="Reply with exactly: nanosage-litellm-ok")
    args = parser.parse_args()

    if not (os.getenv("LITELLM_API_KEY")):
        print("SKIP: LITELLM_API_KEY is not set")
        return 2

    manager = create_llm_manager(
        provider="litellm",
        model=args.model,
        base_url=args.base_url,
        timeout=60,
        max_retries=1,
    )
    response = manager.generate(args.prompt, max_tokens=20)
    if not response.strip():
        print("FAIL: LiteLLM returned an empty response")
        return 1
    print("provider=litellm")
    print(f"model={args.model}")
    print(f"response={response.strip()[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

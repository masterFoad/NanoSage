"""Keyless hosted web search via the You.com MCP free profile.

DuckDuckGo scraping and public SearxNG instances are best-effort: both depend
on HTML that can change under them, and DDG already needed one rescue after the
old duckduckgo-search package stopped returning results. This module speaks the
You.com Model Context Protocol (MCP) streamable-HTTP JSON-RPC endpoint instead:
a hosted, keyless search API (the free profile) that returns ranked results
with URLs and snippets.

No API key, account, or payment is required for the free profile
(https://api.you.com/mcp?profile=free). Setting YOUCOM_API_KEY (or YDC_API_KEY)
switches to the authenticated profile, and YOUCOM_MCP_URL points at any other
MCP endpoint verbatim. The engine is opt-in (see youcom_search in
config.example.yaml / --youcom_search); the default search chain is unchanged.

Only the module-level parsing helpers are exercised by tests: no test needs
network access, matching the scholarly.py arrangement.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

FREE_PROFILE_URL = "https://api.you.com/mcp?profile=free"  # keyless; no API key needed
AUTHENTICATED_URL = "https://api.you.com/mcp"

DEFAULT_TIMEOUT = 30.0
TOOL_NAME = "you-search"
_PROTOCOL_VERSION = "2025-03-26"


@dataclass
class YouComResult:
    """One web result: URL, title, and a short snippet."""

    title: str
    url: str
    description: str


def resolve_endpoint(
    url: Optional[str] = None, api_key: Optional[str] = None
) -> str:
    """Explicit argument wins, then env overrides, then the keyless default."""
    if url:
        return url
    env_url = os.getenv("YOUCOM_MCP_URL")
    if env_url:
        return env_url
    key = api_key or os.getenv("YOUCOM_API_KEY") or os.getenv("YDC_API_KEY")
    if key:
        return AUTHENTICATED_URL
    return FREE_PROFILE_URL


def parse_mcp_frames(raw: str) -> List[Dict[str, Any]]:
    """Parse a streamable-HTTP MCP response body into JSON-RPC frames.

    The body is either an SSE stream (``data:`` lines, events separated by
    blank lines) or a single plain JSON object. Lines are split on ASCII
    newlines only: str.splitlines() would also split on U+0085/U+2028/U+2029,
    which are legal inside JSON string values and would corrupt the payload.
    Non-JSON data lines (heartbeats, junk) are skipped, not fatal.
    """
    frames: List[Dict[str, Any]] = []
    data_lines: List[str] = []

    def flush() -> None:
        if not data_lines:
            return
        data = "\n".join(data_lines)
        data_lines.clear()
        try:
            payload = json.loads(data)
        except ValueError:
            return
        if isinstance(payload, dict):
            frames.append(payload)

    for line in raw.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        if line.startswith(":"):
            continue  # SSE comment / heartbeat
        if line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
        elif line == "":
            flush()
        # event:/id:/retry: carry no payload for us
    flush()

    if frames:
        return frames
    body = raw.strip()
    if body.startswith("{"):
        try:
            payload = json.loads(body)
        except ValueError:
            return []
        if isinstance(payload, dict):
            return [payload]
    return []


def result_payload(frames: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the first frame that carries a JSON-RPC result or error.

    Progress/log notifications ({"method": "notifications/...", "params": ...})
    may interleave with the response; they are ignored here.
    """
    for frame in frames:
        if "result" in frame or "error" in frame:
            return frame
    return None


def extract_web_results(result: Any) -> List[Dict[str, Any]]:
    """Pull the web-results list out of a tools/call result.

    The endpoint answers in two shapes: ``structuredContent.results.web`` on
    the wire, or the same JSON rendered as a string in ``content[0].text``
    (some clients only read content). Both are handled; anything else is an
    empty list, never an exception.
    """
    if not isinstance(result, dict):
        return []
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        web = structured.get("results", {}).get("web")
        if isinstance(web, list):
            return [r for r in web if isinstance(r, dict)]
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                parsed = json.loads(text)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                web = parsed.get("results", {}).get("web")
                if isinstance(web, list):
                    return [r for r in web if isinstance(r, dict)]
    return []


def to_youcom_results(items: List[Dict[str, Any]], limit: Optional[int] = None) -> List[YouComResult]:
    """Map raw web dicts to YouComResult, skipping URL-less entries."""
    results: List[YouComResult] = []
    for item in items:
        url = item.get("url") or item.get("href")
        if not isinstance(url, str) or not url:
            continue
        title = item.get("title")
        description = item.get("description")
        if not isinstance(description, str) or not description:
            description = ""
        if not description:
            contents = item.get("contents")
            if isinstance(contents, dict):
                highlights = contents.get("highlights")
                if isinstance(highlights, list) and highlights and isinstance(highlights[0], str):
                    description = highlights[0]
        results.append(YouComResult(
            title=title if isinstance(title, str) else "",
            url=url,
            description=description,
        ))
        if limit is not None and len(results) >= limit:
            break
    return results


async def search_youcom(
    query: str,
    limit: int = 25,
    url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> List[YouComResult]:
    """Run one you-search call through the MCP endpoint and return results.

    Performs the standard handshake (initialize -> notifications/initialized
    -> tools/call), forwarding the Mcp-Session-Id when the server issues one.
    Failures raise RuntimeError; the engine layer logs and returns [] so the
    remaining engines still run.
    """
    import aiohttp  # core dependency of web_crawler; imported lazily so the
    # pure helpers above stay importable in minimal environments.

    endpoint = resolve_endpoint(url, api_key)
    key = api_key or os.getenv("YOUCOM_API_KEY") or os.getenv("YDC_API_KEY")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if endpoint == AUTHENTICATED_URL and not key:
        logging.warning("You.com: authenticated profile selected but no API key is set")

    request_timeout = aiohttp.ClientTimeout(total=timeout)

    async def _post(session: "aiohttp.ClientSession", payload: Dict[str, Any]) -> Dict[str, Any]:
        async with session.post(endpoint, json=payload, headers=headers) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"You.com MCP request failed with HTTP {resp.status}")
            session_id = resp.headers.get("Mcp-Session-Id")
            if session_id:
                headers["Mcp-Session-Id"] = session_id
            frames = parse_mcp_frames(body)
            frame = result_payload(frames)
            if frame is None:
                raise RuntimeError("You.com MCP response carried no result frame")
            return frame

    async with aiohttp.ClientSession(timeout=request_timeout) as session:
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "nanosage", "version": "0.2.0"},
            },
        }
        init_frame = await _post(session, init_req)
        if "error" in init_frame:
            raise RuntimeError(f"You.com MCP initialize failed: {init_frame['error']}")
        notify_req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        async with session.post(endpoint, json=notify_req, headers=headers) as resp:
            if resp.status not in (200, 202, 204):
                raise RuntimeError(f"You.com MCP initialized-notification failed with HTTP {resp.status}")
        call_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": TOOL_NAME, "arguments": {"query": query, "count": limit}},
        }
        call_frame = await _post(session, call_req)
        if "error" in call_frame:
            raise RuntimeError(f"You.com {TOOL_NAME} failed: {call_frame['error']}")
        items = extract_web_results(call_frame.get("result"))
        return to_youcom_results(items, limit=limit)
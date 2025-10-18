#!/usr/bin/env python3
"""
MetaSearch Crawler (free + fast)
--------------------------------
A plug-and-play upgrade to your original script that:
- Fans out queries and auto-falls back to other free engines if DuckDuckGo rate-limits.
- Uses a pluggable multi-engine interface (DDG → SearxNG → optional Wikipedia/ArXiv).
- Reranks for quality, recency, and domain diversity.
- Downloads concurrently with retries, robots.txt respect, size caps, and URL hashing.
- Extracts clean text (trafilatura → readability-lxml → BeautifulSoup), and PDFs via PyMuPDF.
- Emits a sidecar JSON metadata file for each download.
- Includes a tiny CLI: see bottom (`python metasearch_crawler.py --help`).

Dependencies (all free):
  pip install ddgs aiohttp bs4 trafilatura readability-lxml python-dateutil pymupdf
Optional:
  pip install aiohttp-client-cache pytesseract ocrmypdf huggingface_hub[hf_xet]

Notes / Ethics:
- Be polite: robots.txt, modest concurrency, and do not hammer public SearxNG instances.
- Some public SearxNG instances come and go; this script discovers a working one at runtime.

"""
from __future__ import annotations

import os
import re
import io
import sys
import json
import time
import math
import hashlib
import random
import asyncio
import logging
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Iterable, Tuple
from urllib.parse import urlparse, quote_plus
from urllib.robotparser import RobotFileParser
from datetime import datetime

# --- Third-party imports (soft-fail where possible) ---
try:
    from ddgs import DDGS  # free text/news/images search
except Exception:  # pragma: no cover
    DDGS = None

try:
    import aiohttp
except Exception as e:
    raise SystemExit("aiohttp is required. pip install aiohttp")

try:
    from bs4 import BeautifulSoup
except Exception:
    raise SystemExit("bs4 is required. pip install bs4")

try:
    import fitz  # PyMuPDF
except Exception:
    raise SystemExit("PyMuPDF is required. pip install pymupdf")

try:
    import dateutil.parser as dparser
except Exception:
    raise SystemExit("python-dateutil is required. pip install python-dateutil")

# Optional article extraction libs
try:
    import trafilatura
except Exception:
    trafilatura = None

try:
    from readability import Document
except Exception:
    Document = None

# Optional caching
try:
    import aiohttp_client_cache
except Exception:
    aiohttp_client_cache = None

# Tavily search
try:
    from langchain_tavily import TavilySearch
    from dotenv import load_dotenv
    load_dotenv()  # Load environment variables
    TAVILY_AVAILABLE = True
except Exception as e:
    TAVILY_AVAILABLE = False
    print(f"Tavily not available: {e}")

__VERSION__ = "0.2.0"

# -------------------- Utilities --------------------

def sanitize_filename(filename: str) -> str:
    """Allow only alphanumerics, dot, underscore, and dash."""
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in filename)


def sanitize_path(path: str) -> str:
    parts = path.split(os.sep)
    sanitized = [sanitize_filename(p) for p in parts if p]
    if path.startswith(os.sep):
        return os.sep + os.sep.join(sanitized)
    return os.sep.join(sanitized)


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


# -------------------- Data Model --------------------

@dataclass
class SearchResult:
    title: str
    href: str
    body: str = ""
    source: str = ""  # which engine produced this
    published: Optional[str] = None


# -------------------- Query Expansion --------------------

RECENCY_WINDOWS = ["d", "w", "m"]  # day, week, month


def expand_queries(keyword: str) -> Tuple[List[str], List[str]]:
    kw = keyword.strip()
    if not kw:
        return [], []
    # Variants for recall
    variants = [
        kw,
        f'"{kw}"',
        f"{kw} filetype:pdf",
        f"{kw} site:gov",
        f"{kw} site:edu",
    ]
    return variants, RECENCY_WINDOWS


# -------------------- Engines --------------------

class BaseEngine:
    name = "base"
    async def search(self, keyword: str, *, max_results: int = 25) -> List[SearchResult]:
        raise NotImplementedError


class DuckDuckGoEngine(BaseEngine):
    name = "ddg"

    def __init__(self, region: str = "wt-wt", safesearch: str = "off"):
        if DDGS is None:
            raise RuntimeError("duckduckgo-search package not available")
        self.region = region
        self.safesearch = safesearch

    async def search(self, keyword: str, *, max_results: int = 25) -> List[SearchResult]:
        results: List[SearchResult] = []
        queries, recency = expand_queries(keyword)
        
        # Try multiple times with delays
        for attempt in range(3):
            try:
                with DDGS() as ddgs:
                    # Add delay between attempts
                    if attempt > 0:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    
                    # Try just the main query first (simpler)
                    try:
                        for r in ddgs.text(keyword, region=self.region, safesearch=self.safesearch, max_results=max_results):
                            href = r.get("href")
                            if not href:
                                continue
                            results.append(SearchResult(
                                title=r.get("title") or "",
                                href=href,
                                body=r.get("body") or "",
                                source=self.name,
                            ))
                            if len(results) >= max_results:
                                break
                    except Exception as inner_e:
                        logging.warning("DDG inner error: %s", inner_e)
                        continue
                    
                    # If we got results, return them
                    if results:
                        return results
                        
            except Exception as e:
                logging.warning("DDG attempt %d error: %s", attempt + 1, e)
                if attempt < 2:  # Don't sleep on last attempt
                    await asyncio.sleep(1)
                    
        return results


class SearxNGEngine(BaseEngine):
    name = "searxng"

    # A small pool of public instances; we pick one that passes a quick health check.
    DEFAULT_ENDPOINTS = [
        "https://searx.be",
        "https://searxng.nicfab.eu",
        "https://search.ononoki.org",
        "https://searx.tiekoetter.com",
        "https://nx.tcit.fr/searx",
    ]

    def __init__(self, endpoints: Optional[List[str]] = None, timeout: float = 8.0):
        self.endpoints = endpoints or self.DEFAULT_ENDPOINTS
        self.timeout = timeout
        self._good_endpoint: Optional[str] = None

    async def _pick_endpoint(self, session: aiohttp.ClientSession) -> Optional[str]:
        if self._good_endpoint:
            return self._good_endpoint
        random.shuffle(self.endpoints)
        for base in self.endpoints:
            try:
                url = base.rstrip("/") + "/search?q=test&format=json&categories=general"
                async with session.get(url, timeout=self.timeout) as r:
                    if r.status == 200:
                        self._good_endpoint = base.rstrip("/")
                        return self._good_endpoint
            except Exception:
                continue
        return None

    async def search(self, keyword: str, *, max_results: int = 25) -> List[SearchResult]:
        results: List[SearchResult] = []
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            base = await self._pick_endpoint(session)
            if not base:
                return results

            queries, recency = expand_queries(keyword)
            to_run = []
            for q in queries:
                to_run.append((q, None))
            for tl in recency:
                to_run.append((keyword, tl))

            async def _one(q: str, tl: Optional[str]):
                params = {
                    "q": q,
                    "format": "json",
                    "categories": "general",
                    "language": "en",
                }
                if tl:
                    params["time_range"] = {"d": "day", "w": "week", "m": "month"}.get(tl, "")
                url = base + "/search"
                try:
                    async with session.get(url, params=params) as r:
                        if r.status != 200:
                            return []
                        data = await r.json()
                except Exception:
                    return []
                out = []
                for item in data.get("results", []):
                    href = item.get("url")
                    if not href:
                        continue
                    out.append(SearchResult(
                        title=item.get("title") or "",
                        href=href,
                        body=item.get("content") or "",
                        source=self.name,
                        published=item.get("publishedDate") or None,
                    ))
                return out

            tasks = [_one(q, tl) for (q, tl) in to_run]
            for chunk in await asyncio.gather(*tasks):
                results.extend(chunk)
        return results


class WikipediaEngine(BaseEngine):
    name = "wikipedia"

    async def search(self, keyword: str, *, max_results: int = 25) -> List[SearchResult]:
        # Simple keyword search using MediaWiki API
        api = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": keyword,
            "format": "json",
            "srlimit": min(max_results, 20),
        }
        results: List[SearchResult] = []
        timeout = aiohttp.ClientTimeout(total=8)
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(api, params=params) as r:
                    if r.status != 200:
                        return results
                    data = await r.json()
            for hit in data.get("query", {}).get("search", []):
                title = hit.get("title")
                href = f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}"
                snippet = BeautifulSoup(hit.get("snippet", ""), "html.parser").get_text(" ", strip=True)
                results.append(SearchResult(title=title, href=href, body=snippet, source=self.name))
        except Exception:
            pass
        return results


class BraveSearchEngine(BaseEngine):
    name = "brave"
    
    async def search(self, keyword: str, *, max_results: int = 25) -> List[SearchResult]:
        """Brave Search API - free tier available"""
        results: List[SearchResult] = []
        
        # Brave Search API (free tier: 2000 queries/month)
        api_url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": "BSA"  # Free tier token
        }
        
        params = {
            "q": keyword,
            "count": min(max_results, 20),
            "offset": 0,
            "mkt": "en-US",
            "safesearch": "moderate"
        }
        
        timeout = aiohttp.ClientTimeout(total=10)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(api_url, params=params) as r:
                    if r.status == 200:
                        data = await r.json()
                        web_results = data.get("web", {}).get("results", [])
                        
                        for item in web_results:
                            results.append(SearchResult(
                                title=item.get("title", ""),
                                href=item.get("url", ""),
                                body=item.get("description", ""),
                                source=self.name
                            ))
                    else:
                        logging.warning("Brave API error: status %s", r.status)
                        
        except Exception as e:
            logging.warning("Brave search error: %s", e)
            
        return results


class TavilyEngine(BaseEngine):
    name = "tavily"
    
    def __init__(self):
        if not TAVILY_AVAILABLE:
            raise RuntimeError("langchain-tavily package not available")
        # Check for API key
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise RuntimeError("TAVILY_API_KEY environment variable not set")
        self.tavily = TavilySearch(max_results=10)
    
    async def search(self, keyword: str, *, max_results: int = 25) -> List[SearchResult]:
        """Tavily Search API - fast and reliable"""
        results: List[SearchResult] = []
        
        try:
            # Tavily search is synchronous, so we run it in a thread
            import asyncio
            loop = asyncio.get_event_loop()
            search_response = await loop.run_in_executor(
                None, 
                lambda: self.tavily.invoke({"query": keyword})
            )
            
            # Tavily returns a dict with 'results' key
            if isinstance(search_response, dict):
                search_results = search_response.get("results", [])
            else:
                # Sometimes it returns a list directly
                search_results = search_response if isinstance(search_response, list) else []
            
            for item in search_results:
                if isinstance(item, dict):
                    results.append(SearchResult(
                        title=item.get("title", ""),
                        href=item.get("url", ""),
                        body=item.get("content", ""),
                        source=self.name
                    ))
                    if len(results) >= max_results:
                        break
                    
        except Exception as e:
            logging.warning("Tavily search error: %s", e)
            
        return results


# -------------------- Reranker & Deduper --------------------

GOOD_DOMAINS = (".gov", ".edu", "arxiv.org", "acm.org", "ieee.org", "who.int", "un.org")
BAD_HINTS = ("pinterest.", "quora.", "/tag/", "/category/")


def try_parse_date(text: str) -> Optional[datetime]:
    try:
        dt = dparser.parse(text, fuzzy=True, default=datetime(1970, 1, 1))
        return dt
    except Exception:
        return None


def score_result(item: SearchResult, keyword: str) -> float:
    href = item.href or ""
    title = (item.title or "").lower()
    body = (item.body or "").lower()
    host = urlparse(href).netloc.lower()

    is_good = any(host.endswith(d) for d in GOOD_DOMAINS)
    has_bad = any(h in href for h in BAD_HINTS)

    kw = keyword.lower()
    title_score = 2.0 if kw in title else 0.0
    body_score = 1.0 if kw in body else 0.0
    domain_score = 2.0 if is_good else 0.0
    penalty = -2.0 if has_bad else 0.0

    # recency heuristic
    dt = None
    if item.published:
        dt = try_parse_date(item.published)
    if not dt:
        dt = try_parse_date(body) or try_parse_date(title)
    recency = 0.0
    if dt:
        days = max(1, (datetime.utcnow() - dt).days)
        if days < 30:
            recency = 2.0
        elif days < 180:
            recency = 1.0

    return title_score + body_score + domain_score + recency + penalty


def rerank(results: List[SearchResult], keyword: str, per_domain_cap: int = 3) -> List[SearchResult]:
    # dedupe by href preserving first occurrence
    seen = set()
    deduped = []
    for r in results:
        if r.href and r.href not in seen:
            seen.add(r.href)
            deduped.append(r)
    # score
    deduped.sort(key=lambda r: score_result(r, keyword), reverse=True)
    # diversity
    out, counts = [], {}
    for r in deduped:
        dom = urlparse(r.href).netloc
        counts.setdefault(dom, 0)
        if counts[dom] < per_domain_cap:
            counts[dom] += 1
            out.append(r)
    return out


# -------------------- Downloader (fast + safe) --------------------

_robots_cache: Dict[str, Optional[RobotFileParser]] = {}


async def robots_allowed(session: aiohttp.ClientSession, url: str, user_agent: str = "Mozilla/5.0") -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base in _robots_cache:
        rp = _robots_cache[base]
    else:
        rp = RobotFileParser()
        try:
            async with session.get(base + "/robots.txt", timeout=5) as resp:
                if resp.status == 200:
                    txt = await resp.text()
                    rp.parse(txt.splitlines())
                else:
                    rp = None
        except Exception:
            rp = None
        _robots_cache[base] = rp
    return True if rp is None else rp.can_fetch(user_agent, url)


async def fetch_one(session: aiohttp.ClientSession, url: str, dest_dir: str,
                    max_bytes: int = 8_000_000, tries: int = 3) -> Optional[Dict[str, Any]]:
    if not await robots_allowed(session, url):
        logging.info("Blocked by robots: %s", url)
        return None

    backoff = 0.25
    for attempt in range(tries):
        try:
            # HEAD preflight
            try:
                async with session.head(url, allow_redirects=True, timeout=8) as h:
                    ctype = h.headers.get("Content-Type", "").lower()
                    clen = int(h.headers.get("Content-Length") or 0)
                    if clen and clen > max_bytes:
                        logging.info("Skip big file (%s bytes): %s", clen, url)
                        return None
            except Exception:
                pass

            async with session.get(url, allow_redirects=True,
                                   timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status >= 400:
                    raise aiohttp.ClientResponseError(r.request_info, r.history, status=r.status)
                ctype = r.headers.get("Content-Type", "").lower()
                ext = ".pdf" if ("application/pdf" in ctype or url.lower().endswith(".pdf")) else ".html"
                raw = await r.read()
                if len(raw) > max_bytes:
                    logging.info("Skip big file after GET (%s bytes): %s", len(raw), url)
                    return None
                fname = f"{url_hash(url)}{ext}"
                fpath = os.path.join(dest_dir, fname)
                with open(fpath, "wb") as f:
                    f.write(raw)
                return {"url": url, "file_path": fpath, "content_type": ctype, "size": len(raw)}
        except Exception as e:
            await asyncio.sleep(backoff + random.random() * 0.2)
            backoff *= 2
    return None


async def download_many(urls: List[str], output_dir: str, concurrency: int = 12) -> List[Dict[str, Any]]:
    os.makedirs(output_dir, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)

    # Optional cache for speed-ups across runs
    if aiohttp_client_cache:
        try:
            # Try the newer API first
            from aiohttp_client_cache import SQLiteBackend
            cache_backend = SQLiteBackend(cache_name="metasearch_cache", expire_after=3600)
            # Note: This would need to be integrated with the session, but for now we'll skip caching
            pass
        except (ImportError, AttributeError):
            # Fall back gracefully if caching isn't available
            pass

    timeout = aiohttp.ClientTimeout(total=25)
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip, deflate, br", "Accept": "*/*"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async def _task(u: str):
            async with sem:
                return await fetch_one(session, u, output_dir)
        results = await asyncio.gather(*[_task(u) for u in urls])
    return [r for r in results if r]


# -------------------- Parsing --------------------

def parse_pdf_to_text(pdf_file_path: str, max_pages: int = 10) -> str:
    try:
        doc = fitz.open(pdf_file_path)
        text_parts = []
        for i in range(min(max_pages, doc.page_count)):
            page = doc.load_page(i)
            page_text = page.get_text("text").strip()
            if not page_text:
                page_text = page.get_text("blocks").strip() or ""
            if page_text:
                text_parts.append(page_text)
        text = "\n".join(text_parts)
        if text.strip():
            return text
        # optional: render pages to images here for OCR if configured
        return ""
    except Exception as e:
        logging.warning("PDF parse failed: %s", e)
        return ""


def extract_html_text(html_bytes: bytes) -> str:
    # 1) trafilatura (best effort)
    if trafilatura is not None:
        try:
            txt = trafilatura.extract(html_bytes, include_comments=False, include_links=False)
            if txt and txt.strip():
                return txt
        except Exception:
            pass
    # 2) readability-lxml
    if Document is not None:
        try:
            # Decode bytes to string for readability-lxml
            html_str = html_bytes.decode('utf-8', errors='ignore') if isinstance(html_bytes, bytes) else html_bytes
            doc = Document(html_str)
            html = doc.summary()
            soup = BeautifulSoup(html, "html.parser")
            for t in soup(["script", "style", "noscript"]):
                t.decompose()
            return soup.get_text(" ", strip=True)
        except Exception:
            pass
    # 3) raw BeautifulSoup fallback
    try:
        soup = BeautifulSoup(html_bytes, "html.parser")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        return soup.get_text(" ", strip=True)
    except Exception:
        return ""


def parse_any_to_text(file_path: str, max_pdf_pages: int = 10) -> str:
    if file_path.lower().endswith(".pdf"):
        return parse_pdf_to_text(file_path, max_pages=max_pdf_pages)
    with open(file_path, "rb") as f:
        raw = f.read()
    return extract_html_text(raw)


# -------------------- Engine Orchestration --------------------

class EngineManager:
    """Try engines in order; if one fails/empty (rate-limited), fall through to the next."""

    def __init__(self, engines: List[BaseEngine]):
        self.engines = engines

    async def search(self, keyword: str, max_results: int = 30) -> List[SearchResult]:
        aggregate: List[SearchResult] = []
        for eng in self.engines:
            try:
                chunk = await eng.search(keyword, max_results=max_results)
            except Exception as e:
                logging.warning("engine %s error: %s", eng.name, e)
                chunk = []
            if chunk:
                aggregate.extend(chunk)
            # If we already have a reasonable set, we can stop early
            if len(aggregate) >= max_results * 2:
                break
        return aggregate


# -------------------- Main Orchestration --------------------

async def search_and_download(keyword: str, out_dir: str = "downloaded_webpages",
                              top_n: int = 20, concurrency: int = 12,
                              include_wikipedia: bool = False) -> List[Dict[str, Any]]:
    engines: List[BaseEngine] = []
    
    # 1) Tavily first (most reliable, requires API key)
    if TAVILY_AVAILABLE:
        try:
            engines.append(TavilyEngine())
        except Exception as e:
            logging.warning("Tavily engine failed: %s", e)
    
    # 2) DDG fallback (fast, free)
    if DDGS is not None:
        try:
            engines.append(DuckDuckGoEngine())
        except Exception:
            pass
    
    # 3) SearxNG fallback (auto-discover a healthy instance)
    engines.append(SearxNGEngine())
    
    # 4) Optional: Wikipedia for strong canonical pages
    if include_wikipedia:
        engines.append(WikipediaEngine())

    manager = EngineManager(engines)
    raw_results = await manager.search(keyword, max_results=30)

    ranked = rerank(raw_results, keyword, per_domain_cap=3)[:top_n]
    urls = [r.href for r in ranked if r.href]

    pages = await download_many(urls, out_dir, concurrency=concurrency)

    # parse + sidecar metadata
    parsed = []
    for r, page in zip(ranked, pages):
        text = parse_any_to_text(page["file_path"]) or ""
        preview = (text[:800] + "…") if text else ""
        sidecar = {
            "keyword": keyword,
            "source_engine": r.source,
            "title": r.title,
            "url": page["url"],
            "file_path": page["file_path"],
            "content_type": page.get("content_type", ""),
            "size": page.get("size", 0),
            "downloaded_at": datetime.utcnow().isoformat() + "Z",
            "published_hint": r.published,
            "text_preview": preview,
            "version": __VERSION__,
        }
        # write sidecar JSON next to file
        meta_path = page["file_path"] + ".json"
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(sidecar, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        parsed.append({**page, "meta": sidecar})

    return parsed


# -------------------- CLI --------------------

def _configure_logging(verbosity: int):
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="MetaSearch Crawler (free + fast)")
    p.add_argument("keyword", help="Search keyword / query string")
    p.add_argument("--out", default="downloaded_webpages", help="Output directory")
    p.add_argument("--top", type=int, default=20, help="How many URLs to download after rerank")
    p.add_argument("--concurrency", type=int, default=12, help="Concurrent downloads")
    p.add_argument("--wikipedia", action="store_true", help="Include Wikipedia fallback engine")
    p.add_argument("-v", action="count", default=0, help="Verbosity (-v, -vv)")

    args = p.parse_args(argv)
    _configure_logging(args.v)

    out_dir = sanitize_path(args.out)

    async def _run():
        pages = await search_and_download(
            keyword=args.keyword,
            out_dir=out_dir,
            top_n=args.top,
            concurrency=args.concurrency,
            include_wikipedia=args.wikipedia,
        )
        # Print a compact table to stdout
        for p in pages:
            meta = p.get("meta", {})
            print(f"- {meta.get('title') or ''}\n  {meta.get('url')}\n  -> {meta.get('file_path')}")

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

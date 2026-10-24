"""Keyless local search and hardened page fetching.

Vendored into NanoSage from the standalone `localfetch` tool so the project stays
self-contained: no path dependency, no separate process, no MCP round-trip. The
functions here are called directly by `web_crawler.py`.

Two capabilities NanoSage's aiohttp path does not have on its own:

* **TLS fingerprint impersonation** (`curl_cffi`). A plain aiohttp request with a
  spoofed User-Agent is trivially fingerprinted and blocked; impersonating a real
  Chrome TLS/HTTP2 handshake gets through where the cheap path 403s.
* **Browser escalation** (`nodriver`). NanoSage cannot render JavaScript, so
  SPA-heavy pages currently extract to nothing and are silently dropped. A real
  browser recovers them.

Both third-party packages are OPTIONAL. Without them this module reports itself
unavailable and NanoSage falls back to its existing engines, exactly like the
`trafilatura` / `DDGS` soft imports elsewhere in the crawler.

Browser escalation is expensive (it launches Chrome), and NanoSage fetches many
pages per run, so it is opt-in and budgeted per run rather than per page. See
`BrowserBudget`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

try:  # TLS-impersonating HTTP client
    from curl_cffi import requests as cffi
except Exception:  # pragma: no cover - optional dependency
    cffi = None

try:  # HTML parsing for the DuckDuckGo fallback
    from lxml import html as lxml_html
except Exception:  # pragma: no cover - optional dependency
    lxml_html = None

try:
    import trafilatura
except Exception:  # pragma: no cover - optional dependency
    trafilatura = None


class BlockedError(RuntimeError):
    """Raised when a site actively refused us (challenge page, 403/429/503).

    Distinct from an ordinary fetch failure: retrying the same URL over a weaker
    transport will do strictly worse, so callers should drop the URL rather than
    fall back to a plain HTTP client and save the challenge page as "evidence".
    """


DEFAULT_TIMEOUT = 20

# Markers that appear in the body of a challenge/interstitial page rather than in
# real content.
CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl",
    "cf_chl_opt",
    "checking your browser",
    "enable javascript and cookies to continue",
    "attention required! | cloudflare",
    "ddos protection by",
    "please verify you are a human",
    # Anubis proof-of-work wall (university repositories) and the JS/robot
    # interstitials in front of DOI resolvers and NASA ADS. Measured 2026-10-24:
    # all three copies of a key paper extracted to one of these and were kept
    # as "downloaded", which suppressed the paper's abstract.
    "making sure you're not a bot",
    "verify that you're not a robot",
    "verify you're not a robot",
)

# Below this, whatever came back is a shell, a challenge, or a paywall stub.
MIN_YIELD_CHARS = 200

# ...unless the HTML was itself small, in which case the page is simply short and
# there is nothing for a browser to render that we do not already have.
SMALL_PAGE_HTML = 4000


@dataclass
class Hit:
    """One search result, before it is mapped onto the crawler's SearchResult."""

    title: str
    url: str
    snippet: str = ""
    engine: str = ""


@dataclass
class FetchedPage:
    url: str
    final_url: str
    title: str
    text: str
    html: str
    tier: str  # "direct" | "browser"
    escalation: Optional[str] = None


class BrowserBudget:
    """Caps browser escalations for a whole run, not per page.

    A research run fetches `web_search_limit` pages per branch across many
    branches. Escalating each one independently would launch Chrome dozens of
    times and dominate runtime, so the budget is shared and spent in the order
    branches are explored: the most relevant work gets first claim on it.
    """

    def __init__(self, limit: int = 0):
        self.limit = max(0, int(limit))
        self.used = 0

    def claim(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True



def search_available() -> bool:
    """True when the keyless search path can run at all."""
    return cffi is not None and lxml_html is not None


def fetch_available() -> bool:
    """True when the hardened direct-fetch path can run."""
    return cffi is not None


def extract_text(html: str, url: str) -> str:
    """HTML -> text, keeping the document structure NanoSage chunks on.

    Markdown output is deliberate: headings and list structure survive
    `normalize_extracted_text`, which preserves line breaks, so the chunker can
    split on real boundaries and a summarizing model sees an outline rather than
    one long run-on paragraph.

    `favor_precision` is left off on purpose. It makes trafilatura drop
    borderline blocks, and headings are exactly the borderline blocks worth
    keeping here.
    """
    if not html or trafilatura is None:
        return ""
    try:
        return trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            favor_precision=False,
        ) or ""
    except Exception as exc:
        logging.warning("localfetch extraction failed for %s: %s", url, exc)
        return ""


def title_of(html: str, url: str) -> str:
    if not html or trafilatura is None:
        return url
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
        if meta and meta.title:
            return meta.title
    except Exception:
        pass
    return url


def needs_browser(html: str, extracted: str, status: int) -> Optional[str]:
    """Return why a page needs a real browser, or None if the cheap tier sufficed."""
    if status in (403, 429, 503):
        return f"http {status}"
    head = (html or "")[:4000].lower()
    for marker in CHALLENGE_MARKERS:
        if marker in head:
            return "challenge page"
    if not extracted or len(extracted) < MIN_YIELD_CHARS:
        # Low yield from a large document means content is behind JS. Low yield
        # from a small document means the page is just short -- escalating there
        # would launch a browser for every 404 and link-shortener stub.
        if len(html or "") > SMALL_PAGE_HTML or not (extracted or "").strip():
            return "empty extraction (js-rendered or blocked)"
    return None


def _is_hard_block(reason: Optional[str]) -> bool:
    """True when tier 1 was refused outright rather than merely yielding little.

    A short page is still evidence. A CAPTCHA interstitial or a 403 body is not,
    and indexing it would put "Are you a robot?" into the report as a source.
    """
    if not reason:
        return False
    return reason.startswith("http ") or reason == "challenge page" or reason.startswith("direct fetch failed")


def is_challenge_text(text: str) -> bool:
    """True when *extracted* text is a bot challenge rather than page content.

    Defence in depth: any download path can land on an interstitial, and a page
    that extracts to "Checking your browser..." must never reach the index.
    """
    if not text:
        return False
    head = text[:1000].lower()
    if any(marker in head for marker in CHALLENGE_MARKERS):
        return True
    extra = ("cookies must be enabled", "enable cookies for", "recaptcha",
             "verify you are human", "access denied", "request blocked",
             "javascript is disabled", "captcha")
    return any(marker in head for marker in extra) and len(text) < 1200


def _unwrap_ddg(href: str) -> str:
    """DuckDuckGo wraps results in /l/?uddg=<encoded>; hand back the real target."""
    if "uddg=" not in href:
        return href if href.startswith("http") else "https:" + href
    query = parse_qs(urlparse(href).query)
    return unquote(query.get("uddg", [href])[0])


async def search(query: str, limit: int = 8, *, timeout: int = DEFAULT_TIMEOUT) -> List[Hit]:
    """Keyless DuckDuckGo HTML search through an impersonated TLS session.

    This is an undocumented endpoint and will break periodically, which is why
    NanoSage keeps its other engines as fallbacks rather than relying on it.
    """
    if not search_available() or not query.strip():
        return []
    async with cffi.AsyncSession() as session:
        response = await session.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            impersonate="chrome",
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.text

    tree = lxml_html.fromstring(body)
    hits: List[Hit] = []
    # XPath rather than cssselect: that is a separate package, and one optional
    # dependency for one selector is not a trade worth making.
    for node in tree.xpath("//div[contains(@class, 'links_main')]"):
        link = node.xpath(".//a[contains(@class, 'result__a')]")
        if not link:
            continue
        snippet = node.xpath(".//a[contains(@class, 'result__snippet')]")
        url = _unwrap_ddg(link[0].get("href", ""))
        if not url.startswith("http"):
            continue
        hits.append(Hit(
            title=link[0].text_content().strip(),
            url=url,
            snippet=snippet[0].text_content().strip() if snippet else "",
            engine="localfetch-ddg",
        ))
        if len(hits) >= limit:
            break
    return hits


async def _direct(url: str, timeout: int) -> tuple[str, str, int]:
    """curl-cffi with a real Chrome TLS/HTTP2 fingerprint. No browser."""
    async with cffi.AsyncSession() as session:
        response = await session.get(
            url,
            impersonate="chrome",
            timeout=timeout,
            allow_redirects=True,
        )
        return response.text, str(response.url), response.status_code


async def _browser_html(url: str, *, wait: int = 4, headless: bool = False) -> tuple[str, str]:
    """Render a page in a real browser. Imported lazily: nodriver is heavy."""
    import nodriver

    browser = await nodriver.start(headless=headless)
    try:
        tab = await browser.get(url)
        await tab.sleep(wait)
        html = await tab.get_content()
        final_url = getattr(tab, "url", url) or url
        return html, str(final_url)
    finally:
        try:
            browser.stop()
        except Exception:
            pass


async def fetch_page(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    budget: Optional[BrowserBudget] = None,
    browser_wait: int = 4,
    headless: bool = False,
) -> Optional[FetchedPage]:
    """Fetch a page, escalating to a browser only on demonstrated failure.

    Returns None when the page could not be retrieved at all, so callers can fall
    back to NanoSage's own aiohttp downloader.
    """
    if not fetch_available():
        return None

    html, final_url, status, reason = "", url, 0, None
    try:
        html, final_url, status = await _direct(url, timeout)
    except Exception as exc:
        reason = f"direct fetch failed: {type(exc).__name__}"

    if reason is None:
        text = extract_text(html, final_url)
        reason = needs_browser(html, text, status)
        if reason is None:
            return FetchedPage(url, final_url, title_of(html, final_url), text, html, "direct")

    # Tier 2 runs only on demonstrated failure of tier 1, and only within budget.
    if budget is None or not budget.claim():
        # A blocked or challenged page is not thin content, it is *not content*.
        # Returning it would index "Are you a robot?" as evidence, so refuse and
        # let the caller fall back or drop the URL.
        if _is_hard_block(reason):
            raise BlockedError(f"{url}: {reason}")
        if not html:
            return None
        text = extract_text(html, final_url)
        if text.strip():
            return FetchedPage(url, final_url, title_of(html, final_url), text, html,
                               "direct", escalation=f"{reason} (browser budget unavailable)")
        return None

    try:
        html, final_url = await _browser_html(url, wait=browser_wait, headless=headless)
    except Exception as exc:
        logging.warning("Browser escalation failed for %s: %s", url, exc)
        return None

    text = extract_text(html, final_url)
    return FetchedPage(url, final_url, title_of(html, final_url), text, html, "browser",
                       escalation=reason)

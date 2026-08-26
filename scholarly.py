"""Keyless scholarly search across OpenAlex, Europe PMC, and arXiv.

Publisher HTML is the worst possible source for a research agent: Cloudflare and
reCAPTCHA refuse most automated fetches, so branches come back empty and the
report honestly reports nothing. These three APIs are free, need no key, are not
bot-protected, and hand back structured metadata *including the abstract* — which
means a branch can produce real evidence even when every publisher page blocks us.

No API key, no account, and no identifying parameters are sent. OpenAlex and
Crossref offer faster "polite pool" access in exchange for an email address; that
would leak the operator's identity to a third party for a marginal speedup, so it
is deliberately not used.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import quote_plus
from xml.etree import ElementTree

import aiohttp

OPENALEX_URL = "https://api.openalex.org/works"
EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ARXIV_URL = "http://export.arxiv.org/api/query"

DEFAULT_TIMEOUT = 15
_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


@dataclass
class ScholarlyRecord:
    """One work, with the abstract already in hand."""

    title: str
    abstract: str = ""
    url: str = ""          # best fetchable location
    doi: str = ""
    year: Optional[int] = None
    source: str = ""

    def dedupe_key(self) -> str:
        """Prefer DOI; fall back to a normalized title so cross-source hits merge."""
        if self.doi:
            return self.doi.lower()
        return re.sub(r"[^a-z0-9]+", " ", self.title.lower()).strip()


def _clean_doi(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", value.strip(), flags=re.IGNORECASE)


def reconstruct_abstract(inverted_index: Optional[dict]) -> str:
    """Rebuild OpenAlex's inverted abstract index into running text.

    OpenAlex stores abstracts as `{word: [positions]}` (a licensing workaround).
    Positions are authoritative; gaps are possible, so build by index rather than
    assuming a dense sequence.
    """
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    positioned: dict[int, str] = {}
    for word, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                positioned[position] = word
    if not positioned:
        return ""
    return " ".join(positioned[index] for index in sorted(positioned))


def parse_openalex(payload: dict, limit: int) -> List[ScholarlyRecord]:
    records: List[ScholarlyRecord] = []
    for work in (payload or {}).get("results", [])[:limit]:
        if not isinstance(work, dict):
            continue
        title = (work.get("title") or work.get("display_name") or "").strip()
        if not title:
            continue
        open_access = work.get("open_access") or {}
        primary = work.get("primary_location") or {}
        url = open_access.get("oa_url") or primary.get("landing_page_url") or ""
        doi = _clean_doi(work.get("doi") or "")
        if not url and doi:
            url = f"https://doi.org/{doi}"
        records.append(ScholarlyRecord(
            title=title,
            abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
            url=url,
            doi=doi,
            year=work.get("publication_year") if isinstance(work.get("publication_year"), int) else None,
            source="openalex",
        ))
    return records


def parse_europepmc(payload: dict, limit: int) -> List[ScholarlyRecord]:
    results = ((payload or {}).get("resultList") or {}).get("result") or []
    records: List[ScholarlyRecord] = []
    for item in results[:limit]:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip().rstrip(".")
        if not title:
            continue
        # An OA PMC record exposes machine-readable full text; that beats the
        # publisher landing page, which is exactly what tends to be blocked.
        pmcid = item.get("pmcid")
        if item.get("isOpenAccess") == "Y" and pmcid:
            url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        elif pmcid:
            url = f"https://europepmc.org/article/PMC/{pmcid}"
        elif item.get("doi"):
            url = f"https://doi.org/{_clean_doi(item['doi'])}"
        else:
            url = ""
        year = item.get("pubYear")
        records.append(ScholarlyRecord(
            title=title,
            abstract=(item.get("abstractText") or "").strip(),
            url=url,
            doi=_clean_doi(item.get("doi") or ""),
            year=int(year) if str(year).isdigit() else None,
            source="europepmc",
        ))
    return records


def parse_arxiv(xml_text: str, limit: int) -> List[ScholarlyRecord]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        logging.warning("arXiv response was not valid XML: %s", exc)
        return []
    records: List[ScholarlyRecord] = []
    for entry in root.findall("atom:entry", _ARXIV_NS)[:limit]:
        title_node = entry.find("atom:title", _ARXIV_NS)
        summary_node = entry.find("atom:summary", _ARXIV_NS)
        id_node = entry.find("atom:id", _ARXIV_NS)
        title = " ".join((title_node.text or "").split()) if title_node is not None else ""
        if not title:
            continue
        published = entry.find("atom:published", _ARXIV_NS)
        year = None
        if published is not None and published.text and len(published.text) >= 4:
            year = int(published.text[:4]) if published.text[:4].isdigit() else None
        records.append(ScholarlyRecord(
            title=title,
            abstract=" ".join((summary_node.text or "").split()) if summary_node is not None else "",
            url=(id_node.text or "").strip() if id_node is not None else "",
            year=year,
            source="arxiv",
        ))
    return records


def merge_records(groups: List[List[ScholarlyRecord]], limit: int) -> List[ScholarlyRecord]:
    """Interleave sources, dropping duplicates and abstract-less records.

    Round-robin rather than concatenation so one prolific backend cannot crowd
    the others out of the result budget. A record with an abstract wins over a
    duplicate without one, since the abstract is what makes it usable evidence.
    """
    merged: dict[str, ScholarlyRecord] = {}
    order: List[str] = []
    for column in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if column >= len(group):
                continue
            record = group[column]
            key = record.dedupe_key()
            if not key:
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = record
                order.append(key)
            elif not existing.abstract and record.abstract:
                merged[key] = record
    return [merged[key] for key in order][:limit]


async def _get_json(session: aiohttp.ClientSession, url: str) -> Optional[dict]:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        # Several of these APIs answer with a non-JSON content type.
        return json.loads(await response.text())


async def _get_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return await response.text()


async def search_scholarly(query: str, limit: int = 8) -> List[ScholarlyRecord]:
    """Query all three backends concurrently and merge what comes back.

    A backend that errors contributes nothing rather than failing the search: the
    point of having three is that any one of them can be down.
    """
    query = (query or "").strip()
    if not query:
        return []
    per_source = max(1, limit)
    headers = {"User-Agent": "NanoSage/0.2 (research agent)", "Accept": "application/json"}

    async with aiohttp.ClientSession(headers=headers) as session:
        async def openalex() -> List[ScholarlyRecord]:
            url = f"{OPENALEX_URL}?search={quote_plus(query)}&per-page={per_source}"
            return parse_openalex(await _get_json(session, url), per_source)

        async def europepmc() -> List[ScholarlyRecord]:
            url = (f"{EUROPEPMC_URL}?query={quote_plus(query)}&format=json"
                   f"&pageSize={per_source}&resultType=core")
            return parse_europepmc(await _get_json(session, url), per_source)

        async def arxiv() -> List[ScholarlyRecord]:
            url = f"{ARXIV_URL}?search_query=all:{quote_plus(query)}&max_results={per_source}"
            return parse_arxiv(await _get_text(session, url), per_source)

        outcomes = await asyncio.gather(
            openalex(), europepmc(), arxiv(), return_exceptions=True
        )

    groups: List[List[ScholarlyRecord]] = []
    for name, outcome in zip(("openalex", "europepmc", "arxiv"), outcomes):
        if isinstance(outcome, Exception):
            logging.warning("scholarly backend %s failed: %s", name, outcome)
            continue
        groups.append(outcome)
    return merge_records(groups, limit)

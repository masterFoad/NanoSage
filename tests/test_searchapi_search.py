"""Unit tests for the opt-in SearchApi engine (web_crawler.SearchApiEngine).

No network access: aiohttp is replaced with a fake session, the same
arrangement as tests/test_youcom_search.py.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest import mock

import web_crawler


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def fake_session(payload, status=200, calls=None):
    class FakeSession:
        def __init__(self, timeout=None, headers=None):
            self.headers = headers

        def get(self, url, params=None):
            if calls is not None:
                calls.append((url, params, self.headers))
            return FakeResponse(payload, status)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    return FakeSession


class SearchApiEngineTests(unittest.TestCase):
    def _search(self, session, keyword="quantum computing", max_results=25):
        with mock.patch.dict(os.environ, {"SEARCHAPI_API_KEY": "test-key"}), \
                mock.patch("aiohttp.ClientSession", session):
            engine = web_crawler.SearchApiEngine()
            return asyncio.run(engine.search(keyword, max_results=max_results))

    def test_requires_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                web_crawler.SearchApiEngine()

    def test_request_and_mapping(self):
        calls = []
        payload = {"organic_results": [
            {"position": 1, "title": "A", "link": "https://example.test/a", "snippet": "first"},
            {"position": 2, "title": "B", "link": "https://example.test/b", "snippet": "second"},
        ]}
        results = self._search(fake_session(payload, calls=calls))

        self.assertEqual([r.href for r in results], ["https://example.test/a", "https://example.test/b"])
        self.assertEqual(results[0].title, "A")
        self.assertEqual(results[0].body, "first")
        self.assertEqual(results[0].source, "searchapi")
        url, params, headers = calls[0]
        self.assertEqual(url, "https://www.searchapi.io/api/v1/search")
        self.assertEqual(params, {"engine": "google", "q": "quantum computing"})
        # The key goes in the header, never the query string.
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertNotIn("api_key", params)
        self.assertEqual(headers["User-Agent"], "NanoSage")

    def test_skips_non_url_links_and_caps_results(self):
        payload = {"organic_results": [
            {"title": "token", "link": "/search?q=x", "snippet": ""},
            {"title": "A", "link": "https://example.test/a", "snippet": ""},
            {"title": "B", "link": "https://example.test/b", "snippet": ""},
        ]}
        results = self._search(fake_session(payload), max_results=1)
        self.assertEqual([r.href for r in results], ["https://example.test/a"])

    def test_http_error_returns_empty(self):
        self.assertEqual(self._search(fake_session({"error": "Invalid API key"}, status=401)), [])

    def test_unexpected_body_returns_empty(self):
        for payload in ([], "oops", None, {"organic_results": "nope"}, {"error": "quota"}):
            with self.subTest(payload=payload):
                self.assertEqual(self._search(fake_session(payload)), [])

    def test_skips_malformed_entries(self):
        payload = {"organic_results": ["junk", {"link": None}, {"title": "A", "link": "https://example.test/a"}]}
        self.assertEqual([r.href for r in self._search(fake_session(payload))], ["https://example.test/a"])


class SearchAndDownloadWiringTests(unittest.TestCase):
    def test_engine_added_only_with_key_after_serply(self):
        captured = []

        class StopAfterEngines(Exception):
            pass

        def fake_manager(engines):
            captured.append([e.name for e in engines])
            raise StopAfterEngines

        envs = ({}, {"SEARCHAPI_API_KEY": "test-key"},
                {"SERPLY_API_KEY": "test-key", "SEARCHAPI_API_KEY": "test-key"})
        for env in envs:
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(web_crawler, "TAVILY_AVAILABLE", False), \
                    mock.patch.object(web_crawler, "EngineManager", fake_manager):
                with self.assertRaises(StopAfterEngines):
                    asyncio.run(web_crawler.search_and_download("q", scholarly_search=False))

        self.assertNotIn("searchapi", captured[0])
        self.assertEqual(captured[1][0], "searchapi")
        self.assertEqual(captured[2][:2], ["serply", "searchapi"])


if __name__ == "__main__":
    unittest.main()

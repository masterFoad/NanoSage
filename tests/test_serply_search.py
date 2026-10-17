"""Unit tests for the opt-in Serply engine (web_crawler.SerplyEngine).

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


class SerplyEngineTests(unittest.TestCase):
    def _search(self, session, keyword="quantum computing", max_results=25):
        with mock.patch.dict(os.environ, {"SERPLY_API_KEY": "test-key"}), \
                mock.patch("aiohttp.ClientSession", session):
            engine = web_crawler.SerplyEngine()
            return asyncio.run(engine.search(keyword, max_results=max_results))

    def test_requires_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                web_crawler.SerplyEngine()

    def test_request_and_mapping(self):
        calls = []
        payload = {"results": [
            {"title": "A", "link": "https://example.test/a", "description": "first"},
            {"title": "B", "link": "https://example.test/b", "description": "second"},
        ]}
        results = self._search(fake_session(payload, calls=calls))

        self.assertEqual([r.href for r in results], ["https://example.test/a", "https://example.test/b"])
        self.assertEqual(results[0].title, "A")
        self.assertEqual(results[0].body, "first")
        self.assertEqual(results[0].source, "serply")
        url, params, headers = calls[0]
        self.assertEqual(url, "https://api.serply.io/v1/search/")
        # Serply caps num at 10.
        self.assertEqual(params, {"q": "quantum computing", "num": 10})
        self.assertEqual(headers["X-Api-Key"], "test-key")
        self.assertEqual(headers["User-Agent"], "NanoSage")

    def test_skips_non_url_links_and_caps_results(self):
        payload = {"results": [
            {"title": "token", "link": "CAESexample", "description": ""},
            {"title": "A", "link": "https://example.test/a", "description": ""},
            {"title": "B", "link": "https://example.test/b", "description": ""},
        ]}
        results = self._search(fake_session(payload), max_results=1)
        self.assertEqual([r.href for r in results], ["https://example.test/a"])

    def test_http_error_returns_empty(self):
        self.assertEqual(self._search(fake_session({"error": "quota"}, status=402)), [])


class SearchAndDownloadWiringTests(unittest.TestCase):
    def test_engine_added_only_with_key(self):
        captured = []

        class StopAfterEngines(Exception):
            pass

        def fake_manager(engines):
            captured.append([e.name for e in engines])
            raise StopAfterEngines

        for env in ({}, {"SERPLY_API_KEY": "test-key"}):
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(web_crawler, "TAVILY_AVAILABLE", False), \
                    mock.patch.object(web_crawler, "EngineManager", fake_manager):
                with self.assertRaises(StopAfterEngines):
                    asyncio.run(web_crawler.search_and_download("q", scholarly_search=False))

        self.assertNotIn("serply", captured[0])
        self.assertEqual(captured[1][0], "serply")


if __name__ == "__main__":
    unittest.main()

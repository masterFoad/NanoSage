"""Unit tests for the keyless You.com MCP search client (youcom_search).

No network access: only the pure parsing/mapping helpers are exercised, the
same arrangement as tests/test_scholarly.py.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

import youcom_search


def _frame(result=None, error=None, notification=False):
    if notification:
        return {"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": "x"}}
    payload = {"jsonrpc": "2.0", "id": 1}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def _sse(frames):
    body = []
    for f in frames:
        body.append("event: message")
        body.append("data: " + json.dumps(f))
        body.append("")
    return "\n".join(body)


class ParseMcpFramesTests(unittest.TestCase):
    def test_sse_stream_with_notifications(self):
        raw = _sse([
            _frame(notification=True),
            _frame(result={"structuredContent": {"results": {"web": []}}}),
        ])
        frames = youcom_search.parse_mcp_frames(raw)
        self.assertEqual(len(frames), 2)
        self.assertIn("result", frames[1])

    def test_crlf_is_handled(self):
        raw = _sse([_frame(result={"x": 1})]).replace("\n", "\r\n")
        self.assertEqual(len(youcom_search.parse_mcp_frames(raw)), 1)

    def test_unicode_line_separators_do_not_split_payloads(self):
        # U+2028/U+0085 are legal inside JSON strings; str.splitlines() would
        # treat them as line boundaries and corrupt the frame.
        note = "a" + chr(0x2028) + "b" + chr(0x2029) + "c"
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"note": note}}
        raw = "data: " + json.dumps(payload) + "\n"
        frames = youcom_search.parse_mcp_frames(raw)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["result"]["note"], note)

    def test_multiline_data_frames_are_joined(self):
        obj = {"jsonrpc": "2.0", "id": 1, "result": {"k" * 20: "v" * 20}}
        raw = "data: " + json.dumps(obj) + "\n"
        self.assertEqual(len(youcom_search.parse_mcp_frames(raw)), 1)

    def test_plain_json_body(self):
        raw = json.dumps(_frame(result={"a": 1}))
        frames = youcom_search.parse_mcp_frames(raw)
        self.assertEqual(len(frames), 1)
        self.assertIn("result", frames[0])

    def test_garbage_and_empty(self):
        self.assertEqual(youcom_search.parse_mcp_frames(""), [])
        self.assertEqual(youcom_search.parse_mcp_frames(": heartbeat\n\n"), [])
        self.assertEqual(youcom_search.parse_mcp_frames("data: not json\n\n"), [])

    def test_result_payload_skips_notifications(self):
        frames = [
            _frame(notification=True),
            _frame(result={"web": []}),
        ]
        payload = youcom_search.result_payload(frames)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["result"], {"web": []})
        self.assertIsNone(youcom_search.result_payload([_frame(notification=True)]))
        error = youcom_search.result_payload([_frame(error={"message": "bad"})])
        assert error is not None
        self.assertIn("error", error)


class ExtractWebResultsTests(unittest.TestCase):
    def test_structured_content_shape(self):
        result = {"structuredContent": {"results": {"web": [
            {"url": "https://a", "title": "A", "description": "d"},
            "garbage",
            {"title": "no url"},
        ]}}}
        items = youcom_search.extract_web_results(result)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["url"], "https://a")

    def test_content_text_fallback(self):
        inner = {"results": {"web": [{"url": "https://b", "title": "B"}]}}
        result = {"content": [{"type": "text", "text": json.dumps(inner)}]}
        self.assertEqual(youcom_search.extract_web_results(result)[0]["title"], "B")

    def test_garbage_returns_empty(self):
        self.assertEqual(youcom_search.extract_web_results(None), [])
        self.assertEqual(youcom_search.extract_web_results("nope"), [])
        self.assertEqual(youcom_search.extract_web_results({"content": []}), [])


class ToYoucomResultsTests(unittest.TestCase):
    def test_maps_and_skips_urlless(self):
        items = [
            {"url": "https://a", "title": "A", "description": "d1"},
            {"title": "no url"},
            {"url": "https://c", "title": "C"},
        ]
        records = youcom_search.to_youcom_results(items)
        self.assertEqual([r.url for r in records], ["https://a", "https://c"])
        self.assertEqual(records[1].description, "")

    def test_highlight_fallback_for_missing_description(self):
        items = [{
            "url": "https://a",
            "title": "A",
            "contents": {"highlights": ["first highlight", "second"]},
        }]
        record = youcom_search.to_youcom_results(items)[0]
        self.assertEqual(record.description, "first highlight")

    def test_limit_caps_output(self):
        items = [{"url": "https://x%d" % i, "title": str(i)} for i in range(10)]
        self.assertEqual(len(youcom_search.to_youcom_results(items, limit=3)), 3)


class ResolveEndpointTests(unittest.TestCase):
    def tearDown(self):
        for var in ("YOUCOM_MCP_URL", "YOUCOM_API_KEY", "YDC_API_KEY"):
            os.environ.pop(var, None)

    def test_defaults_and_env(self):
        self.assertEqual(
            youcom_search.resolve_endpoint(),
            "https://api.you.com/mcp?profile=" + "free",
        )
        os.environ["YOUCOM_MCP_URL"] = "https://example.test/mcp"
        self.assertEqual(youcom_search.resolve_endpoint(), "https://example.test/mcp")
        os.environ.pop("YOUCOM_MCP_URL")
        os.environ["YOUCOM_API_KEY"] = "k"
        self.assertEqual(
            youcom_search.resolve_endpoint(),
            "https://api.you.com/mcp",
        )
        self.assertEqual(
            youcom_search.resolve_endpoint(url="https://explicit.test"),
            "https://explicit.test",
        )


class SearchYoucomTests(unittest.TestCase):
    def setUp(self):
        self.call_headers = None
        self.call_args = None

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_live_shape_through_mocked_aiohttp(self):
        """End-to-end through the client with a fake endpoint (no network).

        Exercises the full handshake: initialize -> initialized
        notification -> tools/call, plus session-id passthrough and SSE
        parsing against frames captured from the real endpoint's shape.
        """
        web = [{"url": "https://example.test/x", "title": "X", "description": "d"}]
        call_body = _sse([
            _frame(notification=True),
            _frame(result={"structuredContent": {"results": {"web": web}}}),
        ])
        init_body = _sse([_frame(result={"protocolVersion": "2025-03-26"})])

        class FakeResponse:
            def __init__(self, body, status=200, headers=None):
                self._body = body
                self.status = status
                self.headers = headers or {}

            async def text(self):
                return self._body

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakePost:
            def __init__(self, outer):
                self.outer = outer
                self.calls = []

            def __call__(self, url, json=None, headers=None):
                self.calls.append((url, json, headers))
                method = json.get("method")
                if method == "initialize":
                    return FakeResponse(init_body, headers={"Mcp-Session-Id": "sid-1"})
                if method == "notifications/initialized":
                    return FakeResponse("", status=202)
                if method == "tools/call":
                    self.outer.call_headers = headers
                    self.outer.call_args = json["params"]["arguments"]
                    return FakeResponse(call_body)
                raise AssertionError("unexpected method " + str(method))

        class FakeSession:
            def __init__(self, timeout=None):
                pass

            def post(self, url, **kw):
                return fake_post(url, **kw)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        fake_post = FakePost(self)

        with mock.patch("aiohttp.ClientTimeout", return_value=None), \
                mock.patch("aiohttp.ClientSession", FakeSession):
            records = self._run(youcom_search.search_youcom("quantum computing", limit=3))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].url, "https://example.test/x")
        assert self.call_args is not None
        self.assertEqual(self.call_args["query"], "quantum computing")
        self.assertEqual(self.call_args["count"], 3)
        # session id captured from initialize must be forwarded to tools/call
        assert self.call_headers is not None
        self.assertEqual(self.call_headers.get("Mcp-Session-Id"), "sid-1")

    def test_error_frame_raises(self):
        error_body = _sse([_frame(error={"message": "boom"})])
        init_body = _sse([_frame(result={"protocolVersion": "2025-03-26"})])

        class FakeResponse:
            def __init__(self, body, status=200):
                self._body = body
                self.status = status
                self.headers = {}

            async def text(self):
                return self._body

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def __init__(self, timeout=None):
                pass

            def post(self, url, json=None, headers=None):
                if json.get("method") == "initialize":
                    return FakeResponse(init_body)
                if json.get("method") == "notifications/initialized":
                    return FakeResponse("", status=202)
                return FakeResponse(error_body)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with mock.patch("aiohttp.ClientTimeout", return_value=None), \
                mock.patch("aiohttp.ClientSession", FakeSession):
            with self.assertRaises(RuntimeError):
                self._run(youcom_search.search_youcom("q"))

    def test_http_failure_raises(self):
        class FakeResponse:
            status = 503

            async def text(self):
                return ""

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def __init__(self, timeout=None):
                pass

            def post(self, url, json=None, headers=None):
                return FakeResponse()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with mock.patch("aiohttp.ClientTimeout", return_value=None), \
                mock.patch("aiohttp.ClientSession", FakeSession):
            with self.assertRaises(RuntimeError):
                self._run(youcom_search.search_youcom("q"))


if __name__ == "__main__":
    unittest.main()
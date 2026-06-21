import json
import unittest
from unittest import mock

from special_days import http_client


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


class GetJsonHeadersTest(unittest.TestCase):
    def _patched(self, captured):
        def fake_urlopen(request, timeout=None, context=None):
            captured["request"] = request
            return _FakeResponse(json.dumps({"ok": True}).encode("utf-8"))

        return mock.patch("special_days.http_client.urllib.request.urlopen", fake_urlopen)

    def test_merges_custom_headers_over_defaults(self):
        captured = {}
        with self._patched(captured):
            out = http_client.get_json("https://x/api", headers={"x-apisports-key": "KEY"})
        self.assertEqual(out, {"ok": True})
        headers = captured["request"].headers
        # urllib title-cases header keys: "x-apisports-key" -> "X-apisports-key".
        self.assertEqual(headers.get("X-apisports-key"), "KEY")
        self.assertIn("User-agent", headers)  # default kept

    def test_no_headers_still_sends_defaults(self):
        captured = {}
        with self._patched(captured):
            http_client.get_json("https://x/api")
        headers = captured["request"].headers
        self.assertIn("User-agent", headers)
        self.assertIn("Accept", headers)

    def test_drops_none_valued_params(self):
        captured = {}
        with self._patched(captured):
            http_client.get_json("https://x/api", params={"a": 1, "b": None})
        self.assertIn("a=1", captured["request"].full_url)
        self.assertNotIn("b=", captured["request"].full_url)


if __name__ == "__main__":
    unittest.main()

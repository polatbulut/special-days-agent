import json
import ssl
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


class BuildSslContextTest(unittest.TestCase):
    def setUp(self):
        http_client._build_ssl_context.cache_clear()
        self.addCleanup(http_client._build_ssl_context.cache_clear)

    def test_keeps_default_context_and_adds_certifi_when_available(self):
        context = mock.Mock()
        fake_certifi = mock.Mock()
        fake_certifi.where.return_value = "C:/certifi.pem"
        with mock.patch("special_days.http_client.ssl.create_default_context", return_value=context) as create_ctx:
            with mock.patch.object(http_client, "certifi", fake_certifi):
                out = http_client._build_ssl_context()
        self.assertIs(out, context)
        create_ctx.assert_called_once_with()
        context.load_verify_locations.assert_called_once_with(cafile="C:/certifi.pem")

    def test_returns_default_context_when_certifi_is_unavailable(self):
        context = mock.Mock()
        fake_certifi = mock.Mock()
        fake_certifi.where.side_effect = Exception("boom")
        with mock.patch("special_days.http_client.ssl.create_default_context", return_value=context):
            with mock.patch.object(http_client, "certifi", fake_certifi):
                out = http_client._build_ssl_context()
        self.assertIs(out, context)
        context.load_verify_locations.assert_not_called()

    def test_returns_none_when_default_context_creation_fails(self):
        with mock.patch("special_days.http_client.ssl.create_default_context", side_effect=ssl.SSLError("bad ssl")):
            out = http_client._build_ssl_context()
        self.assertIsNone(out)

    def test_get_json_builds_context_at_request_time(self):
        captured = {}
        context = mock.Mock()

        def fake_urlopen(request, timeout=None, context=None):
            captured["context"] = context
            return _FakeResponse(json.dumps({"ok": True}).encode("utf-8"))

        with mock.patch("special_days.http_client._build_ssl_context", return_value=context) as build_ctx:
            with mock.patch("special_days.http_client.urllib.request.urlopen", fake_urlopen):
                out = http_client.get_json("https://x/api")

        self.assertEqual(out, {"ok": True})
        build_ctx.assert_called_once_with()
        self.assertIs(captured["context"], context)


if __name__ == "__main__":
    unittest.main()

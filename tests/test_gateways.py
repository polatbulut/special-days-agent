import unittest
from unittest import mock

from special_days import gateways

OK_RESPONSE = {"choices": [{"message": {"content": "73"}}]}


class ChatGatewayTest(unittest.TestCase):
    def test_builds_request_and_returns_content(self):
        gw = gateways.ChatGateway("https://api.openai.com/v1/", "gpt-5-mini", api_key="sk-abc")
        with mock.patch("special_days.gateways.post_json", return_value=OK_RESPONSE) as post:
            reply = gw("score this")
        self.assertEqual(reply, "73")
        url, payload = post.call_args.args[0], post.call_args.args[1]
        self.assertEqual(url, "https://api.openai.com/v1/chat/completions")  # trailing slash stripped
        self.assertEqual(payload["model"], "gpt-5-mini")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "score this"}])
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer sk-abc")

    def test_no_api_key_means_no_auth_header(self):
        gw = gateways.ChatGateway("http://localhost:8000/v1", "m")
        with mock.patch("special_days.gateways.post_json", return_value=OK_RESPONSE) as post:
            gw("x")
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])

    def test_malformed_response_raises(self):
        gw = gateways.ChatGateway("http://x/v1", "m")
        with mock.patch("special_days.gateways.post_json", return_value={"oops": 1}):
            with self.assertRaises(ValueError):
                gw("x")


class FactoryTest(unittest.TestCase):
    def test_openai_defaults_model_and_base(self):
        gw = gateways.openai_gateway("sk-x")
        self.assertEqual(gw.base_url, "https://api.openai.com/v1")
        self.assertEqual(gw.model, "gpt-5-mini")
        self.assertEqual(gw.api_key, "sk-x")

    def test_openai_requires_key(self):
        with self.assertRaises(ValueError):
            gateways.openai_gateway(None)

    def test_vllm_requires_base_url_and_model(self):
        with self.assertRaises(ValueError):
            gateways.vllm_gateway(None, "m")
        with self.assertRaises(ValueError):
            gateways.vllm_gateway("http://x/v1", None)

    def test_vllm_defaults_placeholder_key(self):
        gw = gateways.vllm_gateway("http://x:8000/v1", "my-model")
        self.assertEqual(gw.model, "my-model")
        self.assertEqual(gw.api_key, "EMPTY")

    def test_make_gateway_routes(self):
        self.assertEqual(gateways.make_gateway("openai", openai_api_key="k").model, "gpt-5-mini")
        self.assertEqual(
            gateways.make_gateway("vllm", vllm_base_url="http://x/v1", model="m").model, "m"
        )
        with self.assertRaises(ValueError):
            gateways.make_gateway("bogus")


if __name__ == "__main__":
    unittest.main()

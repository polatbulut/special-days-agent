import unittest
from unittest import mock

from special_days import gateways

OK_RESPONSE = {"choices": [{"message": {"content": "73"}}]}


class ChatGatewayTest(unittest.TestCase):
    def test_builds_request_and_returns_content(self):
        gw = gateways.ChatGateway(
            "https://api.openai.com/v1/chat/completions", "gpt-5-mini", api_key="sk-abc"
        )
        with mock.patch("special_days.gateways.post_json", return_value=OK_RESPONSE) as post:
            reply = gw("score this")
        self.assertEqual(reply, "73")
        url, payload = post.call_args.args[0], post.call_args.args[1]
        self.assertEqual(url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(payload["model"], "gpt-5-mini")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "score this"}])
        self.assertNotIn("max_completion_tokens", payload)  # omitted unless set
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer sk-abc")

    def test_includes_max_completion_tokens_when_set(self):
        gw = gateways.ChatGateway("http://x/chat/completions", "m", max_completion_tokens=512)
        with mock.patch("special_days.gateways.post_json", return_value=OK_RESPONSE) as post:
            gw("x")
        self.assertEqual(post.call_args.args[1]["max_completion_tokens"], 512)

    def test_api_key_auth_uses_api_key_header(self):
        gw = gateways.ChatGateway("http://x/chat/completions", "m", api_key="k", auth="api-key")
        with mock.patch("special_days.gateways.post_json", return_value=OK_RESPONSE) as post:
            gw("x")
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["api-key"], "k")
        self.assertNotIn("Authorization", headers)

    def test_no_api_key_means_no_auth_header(self):
        gw = gateways.ChatGateway("http://localhost:8000/v1/chat/completions", "m")
        with mock.patch("special_days.gateways.post_json", return_value=OK_RESPONSE) as post:
            gw("x")
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])

    def test_malformed_response_raises(self):
        gw = gateways.ChatGateway("http://x/chat/completions", "m")
        with mock.patch("special_days.gateways.post_json", return_value={"oops": 1}):
            with self.assertRaises(ValueError):
                gw("x")


class FactoryTest(unittest.TestCase):
    def test_openai_defaults_model_and_url(self):
        gw = gateways.openai_gateway("sk-x")
        self.assertEqual(gw.url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(gw.model, "gpt-5-mini")
        self.assertEqual(gw.auth, "bearer")

    def test_openai_requires_key(self):
        with self.assertRaises(ValueError):
            gateways.openai_gateway(None)

    def test_vllm_requires_base_url_and_model(self):
        with self.assertRaises(ValueError):
            gateways.vllm_gateway(None, "m")
        with self.assertRaises(ValueError):
            gateways.vllm_gateway("http://x/v1", None)

    def test_vllm_builds_url_and_placeholder_key(self):
        gw = gateways.vllm_gateway("http://x:8000/v1/", "my-model")
        self.assertEqual(gw.url, "http://x:8000/v1/chat/completions")
        self.assertEqual(gw.model, "my-model")
        self.assertEqual(gw.api_key, "EMPTY")


class AzureGatewayTest(unittest.TestCase):
    def test_builds_azure_url_and_api_key_header(self):
        gw = gateways.azure_gateway(
            "https://acme.openai.azure.com/", "my-deploy", "az-key", api_version="2024-10-21"
        )
        self.assertEqual(
            gw.url,
            "https://acme.openai.azure.com/openai/deployments/my-deploy/chat/completions"
            "?api-version=2024-10-21",
        )
        self.assertEqual(gw.model, "my-deploy")  # deployment used as the body model
        self.assertEqual(gw.auth, "api-key")
        with mock.patch("special_days.gateways.post_json", return_value=OK_RESPONSE) as post:
            gw("x")
        self.assertEqual(post.call_args.kwargs["headers"]["api-key"], "az-key")
        # reasoning models need a generous completion budget
        self.assertEqual(
            post.call_args.args[1]["max_completion_tokens"],
            gateways.DEFAULT_AZURE_MAX_COMPLETION_TOKENS,
        )

    def test_default_api_version_used(self):
        gw = gateways.azure_gateway("https://acme.openai.azure.com", "dep", "k")
        self.assertIn(f"api-version={gateways.DEFAULT_AZURE_API_VERSION}", gw.url)

    def test_max_completion_tokens_override(self):
        gw = gateways.azure_gateway("https://x", "dep", "k", max_completion_tokens=512)
        self.assertEqual(gw.max_completion_tokens, 512)

    def test_requires_endpoint_deployment_and_key(self):
        with self.assertRaises(ValueError):
            gateways.azure_gateway(None, "dep", "k")
        with self.assertRaises(ValueError):
            gateways.azure_gateway("https://x", None, "k")
        with self.assertRaises(ValueError):
            gateways.azure_gateway("https://x", "dep", None)


class MakeGatewayTest(unittest.TestCase):
    def test_routes(self):
        self.assertEqual(gateways.make_gateway("openai", openai_api_key="k").model, "gpt-5-mini")
        self.assertEqual(
            gateways.make_gateway("vllm", vllm_base_url="http://x/v1", model="m").model, "m"
        )
        azure = gateways.make_gateway(
            "azure", azure_endpoint="https://x.openai.azure.com", azure_api_key="k", model="dep"
        )
        self.assertEqual(azure.auth, "api-key")
        self.assertIn("/openai/deployments/dep/", azure.url)
        with self.assertRaises(ValueError):
            gateways.make_gateway("bogus")


if __name__ == "__main__":
    unittest.main()

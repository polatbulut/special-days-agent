"""LLM gateways for the impact scorer.

OpenAI, vLLM and Azure OpenAI all speak the OpenAI *chat completions* API, so
one small client (:class:`ChatGateway`) covers them — they differ only in the
URL, the model/deployment name and how the API key is sent (``Authorization:
Bearer`` for OpenAI/vLLM, an ``api-key`` header for Azure). A gateway is a
callable ``(prompt: str) -> str`` to plug into
:class:`special_days.scoring.LLMScorer`.
"""

from __future__ import annotations

from .http_client import post_json

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_AZURE_API_VERSION = "2024-10-21"
# Generous output budget for Azure reasoning models (e.g. gpt-5.1): too small a
# value lets reasoning consume it all and return empty content.
DEFAULT_AZURE_MAX_COMPLETION_TOKENS = 16384


class ChatGateway:
    """Calls an OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(
        self,
        url: str,
        model: str,
        api_key: str | None = None,
        *,
        auth: str = "bearer",
        max_completion_tokens: int | None = None,
        timeout: float = 60.0,
    ):
        self.url = url  # the full chat-completions URL (incl. any query string)
        self.model = model
        self.api_key = api_key
        self.auth = auth  # "bearer" -> Authorization: Bearer; "api-key" -> Azure header
        self.max_completion_tokens = max_completion_tokens
        self.timeout = timeout

    def __call__(self, prompt: str) -> str:
        headers = {}
        if self.api_key:
            if self.auth == "api-key":
                headers["api-key"] = self.api_key
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        if self.max_completion_tokens is not None:
            body["max_completion_tokens"] = self.max_completion_tokens
        data = post_json(self.url, body, headers=headers, timeout=self.timeout)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Unexpected chat-completions response: {data!r}") from exc


def openai_gateway(api_key: str | None, model: str | None = None) -> ChatGateway:
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for the openai gateway")
    return ChatGateway(
        f"{DEFAULT_OPENAI_BASE_URL}/chat/completions", model or DEFAULT_OPENAI_MODEL, api_key=api_key
    )


def vllm_gateway(base_url: str | None, model: str | None, api_key: str | None = None) -> ChatGateway:
    if not base_url:
        raise ValueError("VLLM_BASE_URL is required for the vllm gateway")
    if not model:
        raise ValueError("a model name is required for the vllm gateway (--llm-model or VLLM_MODEL)")
    return ChatGateway(f"{base_url.rstrip('/')}/chat/completions", model, api_key=api_key or "EMPTY")


def azure_gateway(
    endpoint: str | None,
    deployment: str | None,
    api_key: str | None,
    api_version: str | None = None,
    max_completion_tokens: int | None = None,
) -> ChatGateway:
    """Azure OpenAI: URL carries the deployment + api-version; auth via api-key.

    Sends ``max_completion_tokens`` (default generous) so reasoning models like
    gpt-5.1 don't exhaust their budget on reasoning and return empty content.
    """
    if not endpoint:
        raise ValueError("AZURE_OPENAI_ENDPOINT is required for the azure gateway")
    if not deployment:
        raise ValueError(
            "an Azure deployment name is required for the azure gateway "
            "(--llm-model or AZURE_OPENAI_DEPLOYMENT)"
        )
    if not api_key:
        raise ValueError("AZURE_OPENAI_API_KEY is required for the azure gateway")
    version = api_version or DEFAULT_AZURE_API_VERSION
    url = (
        f"{endpoint.rstrip('/')}/openai/deployments/{deployment}"
        f"/chat/completions?api-version={version}"
    )
    return ChatGateway(
        url,
        deployment,
        api_key=api_key,
        auth="api-key",
        max_completion_tokens=max_completion_tokens or DEFAULT_AZURE_MAX_COMPLETION_TOKENS,
    )


def make_gateway(
    name: str,
    *,
    openai_api_key: str | None = None,
    vllm_base_url: str | None = None,
    vllm_api_key: str | None = None,
    azure_endpoint: str | None = None,
    azure_api_key: str | None = None,
    azure_api_version: str | None = None,
    azure_max_completion_tokens: int | None = None,
    model: str | None = None,
) -> ChatGateway:
    """Build the gateway for ``name`` (``openai``, ``vllm`` or ``azure``)."""
    if name == "openai":
        return openai_gateway(openai_api_key, model=model)
    if name == "vllm":
        return vllm_gateway(vllm_base_url, model, api_key=vllm_api_key)
    if name == "azure":
        return azure_gateway(
            azure_endpoint,
            model,
            azure_api_key,
            api_version=azure_api_version,
            max_completion_tokens=azure_max_completion_tokens,
        )
    raise ValueError(f"Unknown gateway: {name!r}")

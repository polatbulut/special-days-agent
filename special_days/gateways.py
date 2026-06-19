"""LLM gateways for the impact scorer.

Both OpenAI and vLLM speak the OpenAI *chat completions* API, so one small
client (:class:`ChatGateway`) covers both — they differ only in base URL, model
and credentials. A gateway is a callable ``(prompt: str) -> str`` to plug into
:class:`special_days.scoring.LLMScorer`.
"""

from __future__ import annotations

from .http_client import post_json

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"


class ChatGateway:
    """Calls an OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def __call__(self, prompt: str) -> str:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        data = post_json(
            f"{self.base_url}/chat/completions", body, headers=headers, timeout=self.timeout
        )
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Unexpected chat-completions response: {data!r}") from exc


def openai_gateway(api_key: str | None, model: str | None = None) -> ChatGateway:
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for the openai gateway")
    return ChatGateway(DEFAULT_OPENAI_BASE_URL, model or DEFAULT_OPENAI_MODEL, api_key=api_key)


def vllm_gateway(base_url: str | None, model: str | None, api_key: str | None = None) -> ChatGateway:
    if not base_url:
        raise ValueError("VLLM_BASE_URL is required for the vllm gateway")
    if not model:
        raise ValueError("a model name is required for the vllm gateway (--llm-model or VLLM_MODEL)")
    # vLLM's OpenAI server usually wants *some* token; default to a placeholder.
    return ChatGateway(base_url, model, api_key=api_key or "EMPTY")


def make_gateway(
    name: str,
    *,
    openai_api_key: str | None = None,
    vllm_base_url: str | None = None,
    vllm_api_key: str | None = None,
    model: str | None = None,
) -> ChatGateway:
    """Build the gateway for ``name`` (``openai`` or ``vllm``)."""
    if name == "openai":
        return openai_gateway(openai_api_key, model=model)
    if name == "vllm":
        return vllm_gateway(vllm_base_url, model, api_key=vllm_api_key)
    raise ValueError(f"Unknown gateway: {name!r}")

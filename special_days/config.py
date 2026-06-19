"""Configuration and small environment helpers."""

from __future__ import annotations

import os
from pathlib import Path

TICKETMASTER_API_KEY_ENV = "TICKETMASTER_API_KEY"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
VLLM_BASE_URL_ENV = "VLLM_BASE_URL"
VLLM_API_KEY_ENV = "VLLM_API_KEY"
VLLM_MODEL_ENV = "VLLM_MODEL"

# Default destination markets for the international agent. Kept short on
# purpose — override with `--countries` on the CLI.
DEFAULT_INTERNATIONAL_COUNTRIES = ["DE", "GB", "NL", "FR", "US"]


def load_dotenv(path: str | os.PathLike = ".env") -> None:
    """Load simple ``KEY=VALUE`` lines from a ``.env`` file into ``os.environ``.

    Minimal on purpose (no external dependency). Existing environment
    variables are never overwritten. Missing file is a no-op.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key.startswith("export "):  # tolerate `export KEY=value` lines
            key = key[len("export "):].strip()
        if key and key not in os.environ:
            os.environ[key] = value


def get_ticketmaster_key() -> str | None:
    """Return the Ticketmaster API key from the environment, or ``None``."""
    key = os.environ.get(TICKETMASTER_API_KEY_ENV, "").strip()
    return key or None


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def get_openai_key() -> str | None:
    """Return the OpenAI API key from the environment, or ``None``."""
    return _env(OPENAI_API_KEY_ENV)


def get_vllm_base_url() -> str | None:
    """Return the vLLM server base URL (e.g. http://host:8000/v1), or ``None``."""
    return _env(VLLM_BASE_URL_ENV)


def get_vllm_api_key() -> str | None:
    """Return the vLLM API key, or ``None`` (vLLM often needs no real key)."""
    return _env(VLLM_API_KEY_ENV)


def get_vllm_model() -> str | None:
    """Return the default vLLM model name from the environment, or ``None``."""
    return _env(VLLM_MODEL_ENV)

"""Configuration and small environment helpers."""

from __future__ import annotations

import os
from pathlib import Path

TICKETMASTER_API_KEY_ENV = "TICKETMASTER_API_KEY"
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"

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


def get_anthropic_key() -> str | None:
    """Return the Anthropic API key from the environment, or ``None``."""
    key = os.environ.get(ANTHROPIC_API_KEY_ENV, "").strip()
    return key or None

"""Tiny stdlib HTTP helper — keeps the MVP dependency-free."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "special-days-agent/0.1 (+https://github.com/polatbulut/special-days-agent)"


class HttpError(Exception):
    """Raised when a request fails or returns a non-2xx status."""


def get_json(url: str, params: dict | None = None, timeout: float = 30.0):
    """GET ``url`` (with optional query ``params``) and parse the JSON body.

    ``None``-valued params are dropped. Raises :class:`HttpError` on any
    network or HTTP-status failure so callers can decide whether to skip a
    source or abort.
    """
    if params:
        query = {k: v for k, v in params.items() if v is not None}
        url = f"{url}?{urllib.parse.urlencode(query)}"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} for {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"Network error for {url}: {exc.reason}") from exc

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpError(f"Invalid JSON from {url}: {exc}") from exc

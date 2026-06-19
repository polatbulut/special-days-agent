"""Tiny stdlib HTTP helper."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "special-days-agent/0.1 (+https://github.com/polatbulut/special-days-agent)"

# Use certifi's CA bundle so HTTPS works even when the Python install has no
# system certificates configured (common with Homebrew Python on macOS).
try:
    import certifi

    _SSL_CONTEXT: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except Exception:  # certifi missing -> fall back to the system default
    _SSL_CONTEXT = None


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
        with urllib.request.urlopen(request, timeout=timeout, context=_SSL_CONTEXT) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} for {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"Network error for {url}: {exc.reason}") from exc

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpError(f"Invalid JSON from {url}: {exc}") from exc


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: float = 60.0):
    """POST ``payload`` as JSON to ``url`` and parse the JSON response.

    Raises :class:`HttpError` on network/status failure (the error includes a
    snippet of the response body, which helps debug API 4xx replies).
    """
    body = json.dumps(payload).encode("utf-8")
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_SSL_CONTEXT) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500] if hasattr(exc, "read") else ""
        raise HttpError(f"HTTP {exc.code} for {url}: {exc.reason} — {detail}") from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"Network error for {url}: {exc.reason}") from exc

    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpError(f"Invalid JSON from {url}: {exc}") from exc

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


def _get_bytes(
    url: str,
    params: dict | None,
    timeout: float,
    headers: dict | None,
    accept: str,
) -> bytes:
    """GET ``url`` (with optional query ``params``) and return the raw body.

    Shared plumbing for :func:`get_json` and :func:`get_text`: drops
    ``None``-valued params, sends a default ``User-Agent``/``Accept`` with any
    extra ``headers`` merged over them, and maps network/HTTP-status failures to
    :class:`HttpError`.
    """
    if params:
        query = {k: v for k, v in params.items() if v is not None}
        url = f"{url}?{urllib.parse.urlencode(query)}"

    request_headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_SSL_CONTEXT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} for {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"Network error for {url}: {exc.reason}") from exc


def get_json(
    url: str,
    params: dict | None = None,
    timeout: float = 30.0,
    headers: dict | None = None,
):
    """GET ``url`` (with optional query ``params``) and parse the JSON body.

    ``None``-valued params are dropped. Extra ``headers`` (e.g. an API-key
    header) are merged over the defaults. Raises :class:`HttpError` on any
    network or HTTP-status failure so callers can decide whether to skip a
    source or abort.
    """
    payload = _get_bytes(url, params, timeout, headers, "application/json")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpError(f"Invalid JSON from {url}: {exc}") from exc


def get_text(
    url: str,
    params: dict | None = None,
    timeout: float = 30.0,
    headers: dict | None = None,
    encodings: tuple[str, ...] = ("utf-8", "windows-1252"),
) -> str:
    """GET ``url`` and return the decoded response body as text.

    For scraping HTML pages rather than JSON APIs. Some directories (e.g.
    EventsEye) are served as ``windows-1252``, so each encoding in ``encodings``
    is tried in order, falling back to a lenient UTF-8 decode. Raises
    :class:`HttpError` on network/HTTP-status failure.
    """
    payload = _get_bytes(url, params, timeout, headers, "text/html,application/xhtml+xml")
    for encoding in encodings:
        try:
            return payload.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", "replace")


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

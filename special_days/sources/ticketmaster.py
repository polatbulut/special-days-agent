"""Events source — Ticketmaster Discovery API (free API key).

Docs: https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
Endpoint: GET /discovery/v2/events.json

Covers concerts, sports and arts across 25+ countries including Turkey
(Biletix is Ticketmaster's Turkish brand). Venue coordinates are captured so
the enrichment stage can map each event to the nearest airport.
"""

from __future__ import annotations

import logging
from datetime import date

from ..http_client import get_json
from ..models import SpecialDate

API_URL = "https://app.ticketmaster.com/discovery/v2/events.json"

logger = logging.getLogger(__name__)

# Ticketmaster classification segment -> our impact category.
_SEGMENT_CATEGORY = {
    "Music": "concert",
    "Sports": "sports",
    "Arts & Theatre": "arts",
    "Film": "film",
}


def fetch_events(
    country_code: str,
    api_key: str,
    start: date | None = None,
    end: date | None = None,
    page_size: int = 100,
    max_pages: int = 3,
) -> list[SpecialDate]:
    """Return events for ``country_code``, optionally bounded to ``[start, end]``."""
    country_code = country_code.upper()
    events: list[SpecialDate] = []

    for page in range(max_pages):
        params = {
            "apikey": api_key,
            "countryCode": country_code,
            "size": page_size,
            "page": page,
            "sort": "date,asc",
        }
        if start is not None:
            params["startDateTime"] = f"{start.isoformat()}T00:00:00Z"
        if end is not None:
            params["endDateTime"] = f"{end.isoformat()}T23:59:59Z"

        data = get_json(API_URL, params=params)
        page_events = data.get("_embedded", {}).get("events", [])
        if not page_events:
            break

        for raw in page_events:
            parsed = _parse_event(raw, country_code)
            if parsed is not None:
                events.append(parsed)

        total_pages = data.get("page", {}).get("totalPages", 1)
        if page + 1 >= total_pages:
            break

    return events


def _parse_event(raw: dict, country_code: str) -> SpecialDate | None:
    """Map one Discovery API event object to a :class:`SpecialDate`."""
    name = raw.get("name")
    if not name:
        return None

    dates = raw.get("dates", {})
    start_str = dates.get("start", {}).get("localDate")
    if not start_str:
        return None
    try:
        start_date = date.fromisoformat(start_str)
    except ValueError:
        logger.debug("Skipping event %r: bad start date %r", name, start_str)
        return None

    end_str = dates.get("end", {}).get("localDate")
    try:
        end_date = date.fromisoformat(end_str) if end_str else start_date
    except ValueError:
        end_date = start_date
    if end_date < start_date:  # never emit a backwards range
        end_date = start_date

    city, lat, lon = _venue(raw)
    return SpecialDate(
        event=name,
        start_date=start_date,
        end_date=end_date,
        city=city,
        category=_category(raw),
        country=country_code,
        source="ticketmaster",
        lat=lat,
        lon=lon,
        raw=raw,
    )


def _venue(raw: dict) -> tuple[str, float | None, float | None]:
    """First venue's city and coordinates, or ``("Unknown", None, None)``."""
    for venue in raw.get("_embedded", {}).get("venues", []):
        city = (venue.get("city") or {}).get("name")
        if city:
            location = venue.get("location") or {}
            return city, _to_float(location.get("latitude")), _to_float(location.get("longitude"))
    return "Unknown", None, None


def _category(raw: dict) -> str:
    classifications = raw.get("classifications") or []
    if classifications:
        segment = (classifications[0].get("segment") or {}).get("name")
        return _SEGMENT_CATEGORY.get(segment, "event")
    return "event"


def _to_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None

"""Public-holiday source — Nager.Date (free, no API key required).

Docs: https://date.nager.at/swagger/index.html
Endpoint: GET /api/v3/PublicHolidays/{year}/{countryCode}
"""

from __future__ import annotations

import logging
from datetime import date

from ..http_client import get_json
from ..models import SpecialDate

API_BASE = "https://date.nager.at/api/v3"

logger = logging.getLogger(__name__)


def fetch_holidays(country_code: str, year: int, prefer_local_name: bool = True) -> list[SpecialDate]:
    """Return public holidays for ``country_code`` in ``year``.

    A holiday is a single-day event, so ``start_date == end_date``. Holidays
    are national, so ``city`` is rendered as ``"Nationwide (XX)"``.
    """
    country_code = country_code.upper()
    url = f"{API_BASE}/PublicHolidays/{year}/{country_code}"
    raw = get_json(url)

    holidays: list[SpecialDate] = []
    for item in raw:
        raw_date = item.get("date")
        try:
            day = date.fromisoformat(raw_date)
        except (TypeError, ValueError):
            # Skip a single malformed record rather than losing the whole
            # country (mirrors the per-event guard in the events source).
            logger.debug("Skipping holiday with bad date %r for %s", raw_date, country_code)
            continue
        local = item.get("localName")
        english = item.get("name")
        if prefer_local_name:
            name = local or english
        else:
            name = english or local
        holidays.append(
            SpecialDate(
                event=name or "Unknown holiday",
                start_date=day,
                end_date=day,
                city=f"Nationwide ({country_code})",
                category="public_holiday",
                country=country_code,
                source="nager",
                raw=item,
            )
        )
    return holidays


def fetch_holidays_in_window(country_code: str, start: date, end: date) -> list[SpecialDate]:
    """Return public holidays for ``country_code`` falling within ``[start, end]``.

    The window may span calendar years, so each year it touches is fetched and
    the results are filtered to the window.
    """
    holidays: list[SpecialDate] = []
    for year in range(start.year, end.year + 1):
        for holiday in fetch_holidays(country_code, year):
            if start <= holiday.start_date <= end:
                holidays.append(holiday)
    return holidays

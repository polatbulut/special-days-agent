"""Events source — API-Football (API-Sports) v3 fixtures.

Docs: https://www.api-football.com/documentation-v3
Endpoint: GET https://v3.football.api-sports.io/fixtures
Auth: request header ``x-apisports-key: <key>``

League and cup football (Süper Lig, UEFA club competitions, the top European
leagues) is a major away-fan / visiting-supporter travel driver that
Ticketmaster does not carry, and this API also exposes HISTORICAL fixtures
(useful for backtesting past windows). The ``/fixtures`` endpoint accepts
``league`` + ``season`` + ``from``/``to``, so a date window maps cleanly to
fixtures, past or future.

Notes / free-tier care:
* The endpoint requires a ``season`` alongside ``from``/``to``; we derive the
  season-year(s) the window touches (European August-start convention) and page
  through each league+season — a handful of requests for a 12-month window.
* Fixture timestamps are UTC and this pipeline is timezone-naive, so we record
  the UTC calendar day; a very late kickoff can land on the adjacent local day.
* Fixtures carry no venue coordinates, so ``lat``/``lon`` stay ``None`` and the
  nearest-airport column simply stays blank for these rows.
* Malformed fixtures are skipped rather than aborting the whole league.
"""

from __future__ import annotations

import logging
from datetime import date

from ..http_client import get_json
from ..models import SpecialDate

API_URL = "https://v3.football.api-sports.io/fixtures"

logger = logging.getLogger(__name__)

# Süper Lig — the TurkeyAgent's league.
SUPER_LIG = 203

# Top domestic league per international market. Kept short to respect the
# free-tier request cap (a few paged requests per league per season).
TOP_LEAGUE_BY_COUNTRY = {
    "GB": 39,   # Premier League (England)
    "DE": 78,   # Bundesliga
    "FR": 61,   # Ligue 1
    "NL": 88,   # Eredivisie
    "ES": 140,  # LaLiga
    "IT": 135,  # Serie A
}
# UEFA club competitions (multinational): Champions League, Europa League.
UEFA_LEAGUES = (2, 3)

# API-Football reports the league country as a full name; map the ones we query
# to ISO-3166 alpha-2 to match SpecialDate.country. "World" (UEFA / multinational
# competitions) has no ISO code, so it gets the marker "INT".
_COUNTRY_CODE_BY_NAME = {
    "Turkey": "TR",
    "Türkiye": "TR",
    "England": "GB",
    "Germany": "DE",
    "France": "FR",
    "Netherlands": "NL",
    "Spain": "ES",
    "Italy": "IT",
    "World": "INT",
}


def _season_of(day: date) -> int:
    """The API-Football season-year a date falls in.

    European leagues run August→May and the season is labelled by its starting
    year (the 2025/26 Süper Lig is ``season=2025``). Dates in July onward belong
    to the season starting that year; earlier dates to the previous one.
    """
    return day.year if day.month >= 7 else day.year - 1


def _seasons_for_window(start: date, end: date) -> list[int]:
    """The season-years a window touches (usually one, at most a handful)."""
    return list(range(_season_of(start), _season_of(end) + 1))


def fetch_fixtures_in_window(
    league_id: int,
    api_key: str,
    start: date,
    end: date,
    timeout: float = 30.0,
    max_pages: int = 10,
) -> list[SpecialDate]:
    """Return fixtures for ``league_id`` falling within ``[start, end]``.

    Each season the window touches is queried (the endpoint pairs ``from``/``to``
    with a ``season``) and each season's results are paged through. Fixtures are
    filtered to the window defensively, malformed ones are skipped, and a fixture
    seen more than once (across pages or seasons) is de-duplicated by its fixture
    id — falling back to event+date when the id is absent. ``max_pages`` caps the
    paging per season as a free-tier safety net.
    """
    fixtures: list[SpecialDate] = []
    seen: set = set()
    for season in _seasons_for_window(start, end):
        for page in range(1, max_pages + 1):
            params = {
                "league": league_id,
                "season": season,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "page": page,
            }
            data = get_json(
                API_URL, params=params, headers={"x-apisports-key": api_key}, timeout=timeout
            )
            errors = data.get("errors")
            if errors:  # API-Football reports bad params/quota here, not via HTTP status
                logger.info(
                    "Football league %s season %s page %s returned errors: %r",
                    league_id, season, page, errors,
                )

            response = data.get("response") or []
            if not response:
                break
            for raw in response:
                parsed = _parse_fixture(raw)
                if parsed is None:
                    continue
                if not (start <= parsed.start_date <= end):
                    continue
                fixture_id = (raw.get("fixture") or {}).get("id")
                key = fixture_id if fixture_id is not None else (parsed.event, parsed.start_date)
                if key in seen:
                    continue
                seen.add(key)
                fixtures.append(parsed)

            paging = data.get("paging") or {}
            if paging.get("current", page) >= paging.get("total", 1):
                break
    return fixtures


def _parse_fixture(raw: dict) -> SpecialDate | None:
    """Map one API-Football fixture object to a :class:`SpecialDate`."""
    fixture = raw.get("fixture") or {}
    teams = raw.get("teams") or {}
    home = (teams.get("home") or {}).get("name")
    away = (teams.get("away") or {}).get("name")
    if not home or not away:
        return None

    date_str = fixture.get("date")
    if not date_str:
        return None
    try:
        # ISO 8601 UTC timestamp, e.g. "2026-08-15T16:00:00+00:00"; take the UTC
        # calendar day (this pipeline is timezone-naive).
        match_date = date.fromisoformat(date_str[:10])
    except (TypeError, ValueError):
        logger.debug("Skipping fixture %r: bad date %r", f"{home} vs {away}", date_str)
        return None

    league = raw.get("league") or {}
    venue = fixture.get("venue") or {}
    city = venue.get("city") or "Unknown"

    return SpecialDate(
        event=f"{home} vs {away}",
        start_date=match_date,
        end_date=match_date,  # a fixture is a single-day event
        city=city,
        category="sports",
        country=_country_code(league.get("country")),
        source="football",
        raw=raw,  # API-Football has no venue coordinates -> lat/lon stay None
    )


def _country_code(name) -> str:
    """ISO-3166 alpha-2 for a league's country name; "" if not recognised.

    Guessing from the name (e.g. ``name[:2]``) is avoided on purpose — the first
    two letters of an English country name are usually NOT its ISO code (Denmark
    would become "DE", i.e. Germany). An unrecognised name yields "" so it fails
    neutral rather than emitting a plausible-but-wrong code; extend
    ``_COUNTRY_CODE_BY_NAME`` to add coverage.
    """
    if not name:
        return ""
    return _COUNTRY_CODE_BY_NAME.get(name, "")

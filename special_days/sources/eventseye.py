"""Corporate / B2B events source — EventsEye trade-fair directory (free scrape).

EventsEye (https://www.eventseye.com) is a free, public worldwide directory of
trade shows, exhibitions and B2B expos — exactly the corporate/business-event
signal Ticketmaster and football miss. It exposes no API, no robots.txt and no
anti-bot wall; the per-country listing pages are static, server-rendered HTML
(windows-1252) in a single ``<table class="tradeshows">``. This module fetches
those listings and parses the rows into canonical :class:`SpecialDate` records.

Scope & compliance:
* Only FACTUAL event fields are extracted (name, dates, city, venue, sector
  description, recurrence). Organizer names / emails / phones are deliberately
  NOT collected, to stay clear of GDPR/KVKK personal-data processing.
* Listing pages carry no attendance figures and no venue coordinates, so
  ``lat``/``lon`` stay ``None`` (the nearest-airport column stays blank, like
  football) and the LLM scorer estimates attendance from the event facts.
* Scraping is opt-in (``EVENTSEYE_ENABLED``); page fetches are paced (``pause``)
  and send the project's self-identifying User-Agent (see ``http_client``).

Listing layout (one row per fair):
    | Exhibition Name (+ link + description) | Cycle | City + Venue | Date |
where the date cell is ``MM/DD/YYYY<br><i>N days</i>`` — a single start date plus
a duration, so ``end = start + (N - 1)`` days.
"""

from __future__ import annotations

import html as _html
import logging
import re
import time
import urllib.parse
from datetime import date, timedelta

from ..http_client import get_text
from ..models import SpecialDate
from ..window import overlaps

logger = logging.getLogger(__name__)

BASE_URL = "https://www.eventseye.com/fairs/"
LISTING_URL = BASE_URL + "c1_trade-shows_{slug}.html"

# ISO-3166 alpha-2 -> EventsEye country-slug (the site uses full-name slugs).
# Extend this map to add markets; an unmapped country is skipped, not guessed.
COUNTRY_SLUG = {
    "TR": "turkey",
    "DE": "germany",
    "GB": "uk-united-kingdom",
    "FR": "france",
    "NL": "netherlands",
    "US": "usa-united-states-of-america",
    "ES": "spain",
    "IT": "italy",
}

_TABLE_RE = re.compile(r'<table class="tradeshows">(.*?)</table>', re.DOTALL)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)  # tolerate row attrs (zebra classes)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_NAME_RE = re.compile(r"<b>(.*?)</b>", re.DOTALL)
_DESC_RE = re.compile(r"<i>(.*?)</i>", re.DOTALL)
_DETAIL_RE = re.compile(r'href="(f-[^"]+\.html)"')
_ANCHOR_RE = re.compile(r"<a [^>]*>(.*?)</a>", re.DOTALL)
_ANCHOR_HREF_TEXT_RE = re.compile(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_DURATION_RE = re.compile(r"(\d+)\s*day")
_TAG_RE = re.compile(r"<[^>]+>")


def fetch_events_in_window(
    country_code: str,
    start: date,
    end: date,
    *,
    max_pages: int = 10,
    pause: float = 1.0,
    base_url: str = BASE_URL,
) -> list[SpecialDate]:
    """Return EventsEye trade fairs for ``country_code`` overlapping ``[start, end]``.

    Walks the country listing page and follows its "Next" link, parsing each
    ``<table class="tradeshows">`` row. Rows are sorted ascending by date, so
    once a whole page starts past ``end`` paging stops early (politeness). Records
    are de-duplicated by (event, start) across pages, malformed rows are skipped,
    and ``max_pages`` caps the crawl. ``pause`` seconds elapse between page fetches.
    """
    country_code = country_code.upper()
    slug = COUNTRY_SLUG.get(country_code)
    if slug is None:
        logger.info("EventsEye: no country-slug mapping for %s; skipping", country_code)
        return []

    url = LISTING_URL.format(slug=slug)
    events: list[SpecialDate] = []
    seen: set = set()
    for _page in range(max_pages):
        page = get_text(url)
        table = _TABLE_RE.search(page)
        if table is None:
            break

        parsed_any = False
        all_past_end = True
        for row in _ROW_RE.findall(table.group(1)):
            record = _parse_row(_CELL_RE.findall(row), country_code, base_url)
            if record is None:
                continue
            parsed_any = True
            if record.start_date <= end:
                all_past_end = False
            if not overlaps(record.start_date, record.end_date, start, end):
                continue
            key = (record.event, record.start_date)
            if key in seen:
                continue
            seen.add(key)
            events.append(record)

        # Ascending by date: if every fair on this page already starts after the
        # window, later pages are entirely past it too — stop.
        if parsed_any and all_past_end:
            break
        next_url = _find_next_url(page, url)
        if not next_url or next_url == url:
            break
        url = next_url
        if pause > 0:
            time.sleep(pause)
    return events


def _parse_row(cells: list[str], country_code: str, base_url: str) -> SpecialDate | None:
    """Map one ``<tr>`` (its list of ``<td>`` inner-HTML strings) to a record."""
    if len(cells) < 4:
        return None  # header row (<th> cells) and malformed rows fall out here
    name_cell, cycle_cell, venue_cell, date_cell = cells[0], cells[1], cells[2], cells[3]

    name_match = _NAME_RE.search(name_cell)
    name = _text(name_match.group(1)) if name_match else _text(name_cell)
    if not name:
        return None

    start = _parse_date(date_cell)
    if start is None:
        return None
    duration_match = _DURATION_RE.search(date_cell)
    days = max(1, int(duration_match.group(1))) if duration_match else 1
    end = start + timedelta(days=days - 1)

    cities = [_text(a) for a in _ANCHOR_RE.findall(venue_cell)]
    cities = [c for c in cities if c]
    city = cities[0] if cities else "Unknown"
    venue = cities[1] if len(cities) > 1 else None

    desc_match = _DESC_RE.search(name_cell)
    detail_match = _DETAIL_RE.search(name_cell)
    raw = {
        "name": name,
        "description": _text(desc_match.group(1)) if desc_match else None,
        "city": city,
        "venue": venue,
        "cycle": _text(cycle_cell) or None,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_days": days,
        "country": country_code,
        "url": urllib.parse.urljoin(base_url, detail_match.group(1)) if detail_match else None,
        "source_site": "eventseye",
    }
    return SpecialDate(
        event=name,
        start_date=start,
        end_date=end,
        city=city,
        category="expo",
        country=country_code,
        source="eventseye",
        raw=raw,  # facts only — no organizer PII
    )


def _parse_date(token: str) -> date | None:
    """Parse the leading date out of a date cell.

    EventsEye serves ``MM/DD/YYYY``; if the first field is clearly out of month
    range it is treated as ``DD/MM/YYYY`` instead, so a locale flip can't silently
    invert the date.
    """
    match = _DATE_RE.search(token)
    if not match:
        return None
    first, second, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    month, day = first, second
    if first > 12 and second <= 12:  # must be DD/MM
        month, day = second, first
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _find_next_url(page_html: str, current_url: str) -> str | None:
    """Resolve the "Next" pagination link on a listing page, if any."""
    for href, inner in _ANCHOR_HREF_TEXT_RE.findall(page_html):
        if href and _text(inner).lower() == "next":
            return urllib.parse.urljoin(current_url, _html.unescape(href))
    return None


def _text(fragment: str) -> str:
    """Strip tags and unescape HTML entities, collapsing whitespace."""
    return re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub("", fragment))).strip()

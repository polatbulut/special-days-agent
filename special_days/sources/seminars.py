"""Business seminars / conferences source — ConferenceIndex directory (free scrape).

ConferenceIndex (https://conferenceindex.org) is a free, public worldwide
directory of academic and professional conferences. Its ``business`` discipline
listings (management, marketing, economics, finance, entrepreneurship …) are the
business-seminar signal Ticketmaster, football and the EventsEye trade fairs
miss. ``robots.txt`` is fully permissive (``Disallow:`` empty) and the per-country
listing pages are static, server-rendered HTML, so this module fetches them and
parses the rows into canonical :class:`SpecialDate` records.

Scope & compliance:
* Only FACTUAL fields are extracted (conference name, date, city, detail URL).
  No organizer names / emails / phones — so no GDPR/KVKK personal data.
* Listings carry a single date and no coordinates, so records are single-day and
  ``lat``/``lon`` stay ``None`` (nearest-airport column blank, like football);
  the LLM scorer estimates attendance from the conference facts.
* Scraping is opt-in (``SEMINARS_ENABLED``); page fetches are paced (``pause``)
  and send the project's self-identifying User-Agent (see ``http_client``).

Listing layout (per country page, one month-card per calendar month)::

    <div class="card-header"> ... <strong>July, 2026</strong> ... </div>
    <div class="card-body"><ul class="list-unstyled">
      <li> Jul 29 <a href="/event/…" title="…">Conference title</a> - Istanbul, Turkey </li>
      ...
    </ul></div>

The month-card's ``<strong>Month, YYYY</strong>`` gives the year; each ``<li>``
gives the ``Mon DD`` date, the title and the ``City, Country`` tail.
"""

from __future__ import annotations

import html as _html
import logging
import re
import time
import urllib.parse
from datetime import date

from ..http_client import get_text
from ..models import SpecialDate
from ..window import overlaps

logger = logging.getLogger(__name__)

BASE_URL = "https://conferenceindex.org/conferences"
DEFAULT_DISCIPLINE = "business"

# ISO-3166 alpha-2 -> ConferenceIndex country slug (lowercased full country name).
# The default-market slugs (TR/DE/GB/NL/FR/US) are verified against the live site;
# the rest follow the same convention. An unmapped country is skipped, not guessed.
COUNTRY_SLUG = {
    "TR": "turkey", "DE": "germany", "GB": "united-kingdom", "NL": "netherlands",
    "FR": "france", "US": "united-states",
    "ES": "spain", "IT": "italy", "AT": "austria", "BE": "belgium", "CH": "switzerland",
    "PT": "portugal", "GR": "greece", "IE": "ireland", "PL": "poland", "SE": "sweden",
    "CA": "canada", "AU": "australia", "JP": "japan", "CN": "china", "IN": "india",
    "SG": "singapore", "AE": "united-arab-emirates", "SA": "saudi-arabia", "QA": "qatar",
}

_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# A month-card: the "<strong>Month, YYYY</strong>" header, then the nearest
# following "<ul>…</ul>" list of that month's conferences.
_CARD_RE = re.compile(
    r"<strong>\s*[A-Za-z]+,\s*(\d{4})\s*</strong>.*?<ul[^>]*>(.*?)</ul>", re.DOTALL
)
# One "<li>": "Mon DD <a href=…>Title</a> - City, Country".
_LI_RE = re.compile(
    r'<li>\s*([A-Za-z]{3,})\s+(\d{1,2})\s*'
    r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>\s*-\s*(.*?)</li>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_listing(page_html: str, country_code: str) -> list[SpecialDate]:
    """Parse a ConferenceIndex country page into records (no network).

    The year comes from each month-card header; the month and day from the
    ``<li>``. Rows are de-duplicated by ``(title, date)``; malformed rows are
    skipped.
    """
    records: list[SpecialDate] = []
    seen: set = set()
    for card in _CARD_RE.finditer(page_html):
        year = int(card.group(1))
        for li in _LI_RE.finditer(card.group(2)):
            abbr, day_str, href, title_html, tail = li.groups()
            month = _MONTH_ABBR.get(abbr[:3].lower())
            if month is None:
                continue
            try:
                event_date = date(year, month, int(day_str))
            except ValueError:
                continue
            title = _text(title_html)
            if not title:
                continue
            city = _text(tail).rsplit(",", 1)[0].strip() or "Unknown"
            key = (title, event_date)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                SpecialDate(
                    event=title,
                    start_date=event_date,
                    end_date=event_date,
                    city=city,
                    category="seminar",
                    country=country_code,
                    source="seminars",
                    raw={
                        "name": title,
                        "city": city,
                        "country": country_code,
                        "date": event_date.isoformat(),
                        "url": urllib.parse.urljoin(BASE_URL + "/", href),
                        "discipline": DEFAULT_DISCIPLINE,
                        "source_site": "conferenceindex",
                    },
                )
            )
    return records


def fetch_events_in_window(
    country_code: str,
    start: date,
    end: date,
    *,
    discipline: str = DEFAULT_DISCIPLINE,
    max_pages: int = 10,
    pause: float = 1.0,
    get=get_text,
) -> list[SpecialDate]:
    """Return ConferenceIndex business conferences for ``country_code`` in ``[start, end]``.

    Walks the country listing (``?page=N``), parsing each month-card. Listings are
    date-ascending, so once a whole page starts past ``end`` paging stops early
    (politeness). ``get`` is the page fetcher (injectable for tests); a fetch error
    ends the crawl with whatever was collected so far.
    """
    country_code = country_code.upper()
    slug = COUNTRY_SLUG.get(country_code)
    if slug is None:
        logger.info("seminars: no country-slug mapping for %s; skipping", country_code)
        return []

    base = f"{BASE_URL}/{discipline}/{slug}"
    events: list[SpecialDate] = []
    seen: set = set()
    for page in range(1, max_pages + 1):
        url = base if page == 1 else f"{base}?page={page}"
        try:
            page_records = parse_listing(get(url), country_code)
        except Exception as exc:  # noqa: BLE001 - keep whatever earlier pages produced
            logger.warning("seminars: fetch failed for %s: %s", url, exc)
            break
        if not page_records:
            break  # past the last page

        all_past_end = True
        for record in page_records:
            if record.start_date <= end:
                all_past_end = False
            if not overlaps(record.start_date, record.end_date, start, end):
                continue
            key = (record.event, record.start_date)
            if key in seen:
                continue
            seen.add(key)
            events.append(record)

        if all_past_end:
            break  # ascending: later pages are entirely past the window too
        if pause > 0 and page < max_pages:
            time.sleep(pause)
    return events


def _text(fragment: str) -> str:
    """Strip tags and unescape HTML entities, collapsing whitespace."""
    return re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub("", fragment))).strip()

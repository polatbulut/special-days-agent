"""Religious-holiday source — official Diyanet dates (curated, bundled).

Nager.Date does not return Turkey's *moving* Ramazan/Kurban Bayramı dates, so
they are bundled from official Diyanet announcements (see
``data/diyanet_holidays.json``) and updated yearly. Each record spans the
arife (eve) through the last official day — the travel-relevant window.

Note: government-declared bridge/administrative days (idari izin / köprü) that
extend a bayram are announced ad hoc and are NOT included here.
"""

from __future__ import annotations

import logging
from datetime import date

from ..dataset import load_diyanet
from ..models import SpecialDate
from ..window import overlaps

logger = logging.getLogger(__name__)


def fetch_in_window(start: date, end: date) -> list[SpecialDate]:
    """Return Diyanet religious holidays overlapping ``[start, end]``."""
    holidays: list[SpecialDate] = []
    for item in load_diyanet():
        try:
            holiday_start = date.fromisoformat(item["start"])
            holiday_end = date.fromisoformat(item["end"])
        except (KeyError, TypeError, ValueError):
            logger.debug("Skipping malformed Diyanet record %r", item)
            continue
        if overlaps(holiday_start, holiday_end, start, end):
            holidays.append(
                SpecialDate(
                    event=item["name"],
                    start_date=holiday_start,
                    end_date=holiday_end,
                    city="Nationwide (TR)",
                    category="religious_holiday",
                    country="TR",
                    source="diyanet",
                )
            )
    return holidays

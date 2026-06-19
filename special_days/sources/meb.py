"""School-break source — official MEB academic calendar (curated, bundled).

Turkish school terms have no clean API, so the breaks (mid-term, semester and
summer) are bundled from the published MEB calendar (see
``data/meb_breaks.json``) and updated yearly.
"""

from __future__ import annotations

import logging
from datetime import date

from ..dataset import load_meb
from ..models import SpecialDate
from ..window import overlaps

logger = logging.getLogger(__name__)


def fetch_in_window(start: date, end: date) -> list[SpecialDate]:
    """Return MEB school breaks overlapping ``[start, end]``."""
    breaks: list[SpecialDate] = []
    for item in load_meb():
        try:
            break_start = date.fromisoformat(item["start"])
            break_end = date.fromisoformat(item["end"])
        except (KeyError, TypeError, ValueError):
            logger.debug("Skipping malformed MEB record %r", item)
            continue
        if overlaps(break_start, break_end, start, end):
            breaks.append(
                SpecialDate(
                    event=item["name"],
                    start_date=break_start,
                    end_date=break_end,
                    city="Nationwide (TR)",
                    category="school_holiday",
                    country="TR",
                    source="meb",
                )
            )
    return breaks

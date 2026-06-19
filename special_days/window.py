"""Rolling date-window helpers.

The agent collects a forward-looking window (default: the next 12 months from
today) rather than a fixed calendar year, so a weekly job always looks ahead.
"""

from __future__ import annotations

import calendar
from datetime import date


def add_months(start: date, months: int) -> date:
    """Return ``start`` shifted by ``months`` (clamped to month length)."""
    index = start.month - 1 + months
    year = start.year + index // 12
    month = index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def resolve_window(start: date | None, months: int) -> tuple[date, date]:
    """Return ``(start, end)`` for a window of ``months`` beginning at ``start``.

    ``start`` defaults to today; ``end`` is ``start`` plus ``months`` months.
    """
    start = start or date.today()
    return start, add_months(start, months)


def overlaps(start: date, end: date, window_start: date, window_end: date) -> bool:
    """True if ``[start, end]`` intersects ``[window_start, window_end]``."""
    return start <= window_end and end >= window_start


def is_weekend(day: date) -> bool:
    """True for Saturday/Sunday (Turkey's weekend)."""
    return day.isoweekday() >= 6

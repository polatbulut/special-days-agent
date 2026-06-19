"""Per-day impact weight curves.

Builds a Linear-V weight per day across a date range: the peak (the record's
impact score) at both ends, dipping linearly to ``TROUGH_FRACTION`` of the peak
at the middle. Any weekend day is forced to the peak — weekends are always
peak travel demand.
"""

from __future__ import annotations

from datetime import date, timedelta

from .window import is_weekend

TROUGH_FRACTION = 0.5  # middle of the range dips to ~half the peak; tunable

_ONE_DAY = timedelta(days=1)


def _days(start: date, end: date) -> list[date]:
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += _ONE_DAY
    return days


def weights(
    start: date,
    end: date,
    peak: int,
    trough: float = TROUGH_FRACTION,
) -> tuple[tuple[str, int], ...]:
    """Return ``((iso_date, weight), ...)`` for each day in ``[start, end]``.

    Linear V from ``peak`` at the ends to ``peak * trough`` at the middle;
    weekend days are forced to ``peak``.
    """
    days = _days(start, end)
    n = len(days)
    if n == 1:
        return ((days[0].isoformat(), int(peak)),)

    result = []
    for i, day in enumerate(days):
        if is_weekend(day):
            weight = peak
        else:
            t = i / (n - 1)  # 0..1
            factor = 1 - (1 - trough) * (1 - abs(2 * t - 1))  # 1 at ends, trough at middle
            weight = round(peak * factor)
        result.append((day.isoformat(), int(weight)))
    return tuple(result)

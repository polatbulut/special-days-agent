"""Bridge ("köprü") computation for Turkish holidays.

Extends a holiday's statutory ``[start, end]`` outward to the maximal
contiguous block of non-working days, bridging up to ``G`` working days per
side to reach the adjacent weekend (``G = 1`` for a single-day holiday, ``2``
for a multi-day one). Weekend days are "free" (do not count against ``G``).

Only Turkish holidays are bridged; everything else keeps its statutory range.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import SpecialDate
from .window import is_weekend

_ONE_DAY = timedelta(days=1)


def _extend_forward(end: date, gap_budget: int) -> date:
    """Last day of the block after ``end`` (lookahead: only bridge if a weekend
    is reachable within ``gap_budget`` working days)."""
    cursor = end + _ONE_DAY
    working = 0
    while not is_weekend(cursor):
        working += 1
        if working > gap_budget:
            return end  # weekend too far to bridge
        cursor += _ONE_DAY
    while is_weekend(cursor):  # absorb the whole weekend run
        cursor += _ONE_DAY
    return cursor - _ONE_DAY


def _extend_backward(start: date, gap_budget: int) -> date:
    """First day of the block before ``start`` (mirror of ``_extend_forward``)."""
    cursor = start - _ONE_DAY
    working = 0
    while not is_weekend(cursor):
        working += 1
        if working > gap_budget:
            return start
        cursor -= _ONE_DAY
    while is_weekend(cursor):
        cursor -= _ONE_DAY
    return cursor + _ONE_DAY


def compute_bridge(record: SpecialDate) -> tuple[date, date]:
    """Return ``(bridge_start, bridge_end)`` — the full extended block.

    For non-TR-holiday records this is just the statutory range.
    """
    if not record.is_tr_holiday():
        return record.start_date, record.end_date
    gap_budget = 1 if record.start_date == record.end_date else 2
    return (
        _extend_backward(record.start_date, gap_budget),
        _extend_forward(record.end_date, gap_budget),
    )

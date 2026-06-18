"""Canonical record shared by every source and both agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class SpecialDate:
    """One special date in the shape requested by the business:

        Event  —  start date  —  end date  —  city

    A few extra fields (``category``, ``country``, ``source``) are kept for
    traceability and downstream filtering, but the four fields above are the
    headline output.
    """

    event: str
    start_date: date
    end_date: date
    city: str
    category: str  # "holiday" | "event"
    country: str  # ISO-3166 alpha-2, e.g. "TR"
    source: str  # "nager" | "ticketmaster"

    def sort_key(self) -> tuple[date, str]:
        return (self.start_date, self.event.lower())

    def core_row(self) -> tuple[str, str, str, str]:
        """The four headline fields as strings: (event, start, end, city)."""
        return (
            self.event,
            self.start_date.isoformat(),
            self.end_date.isoformat(),
            self.city,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start_date"] = self.start_date.isoformat()
        d["end_date"] = self.end_date.isoformat()
        return d

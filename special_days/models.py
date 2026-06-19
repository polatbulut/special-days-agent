"""Canonical record shared by every source and both agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class SpecialDate:
    """One special date.

    The headline output is six columns:

        Event — Start date — End date — City — Nearest airport — Impact

    The first four are the original business ask; ``nearest_airport`` (IATA)
    and ``impact_score`` come from the enrichment stage. The remaining fields
    (``category``, ``country``, ``source``, ``lat``/``lon``,
    ``airport_distance_km``) aid traceability and are emitted in JSON.
    """

    event: str
    start_date: date
    end_date: date
    city: str
    category: str  # public_holiday | religious_holiday | school_holiday | concert | sports | arts | film | event
    country: str  # ISO-3166 alpha-2, e.g. "TR"
    source: str  # nager | diyanet | meb | ticketmaster
    lat: float | None = None
    lon: float | None = None
    nearest_airport: str | None = None  # IATA code (enrichment)
    airport_distance_km: float | None = None  # enrichment
    impact_score: int | None = None  # 0-100 (enrichment)

    def sort_key(self) -> tuple[date, str]:
        return (self.start_date, self.event.lower())

    def core_row(self) -> tuple[str, str, str, str, str, str]:
        """The six headline fields as strings."""
        return (
            self.event,
            self.start_date.isoformat(),
            self.end_date.isoformat(),
            self.city,
            self.nearest_airport or "",
            "" if self.impact_score is None else str(self.impact_score),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["start_date"] = self.start_date.isoformat()
        data["end_date"] = self.end_date.isoformat()
        return data

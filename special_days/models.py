"""Canonical record shared by every source and both agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class SpecialDate:
    """One special date.

    The headline output is eight columns:

        Event — Start date — End date — City — Nearest airport — Impact
        — Bridge start — Bridge end

    The first four are the original business ask; ``nearest_airport``,
    ``impact_score`` and the köprü ``bridge_*`` / per-day ``impact_by_day*``
    fields come from the enrichment stage. The remaining fields (``category``,
    ``country``, ``source``, ``lat``/``lon``, ``airport_distance_km``) aid
    traceability and are emitted in JSON.
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
    impact_score: int | None = None  # 0-100 peak (enrichment)
    bridge_start: date | None = None  # köprü-extended block (enrichment)
    bridge_end: date | None = None
    # Per-day weight curves, stored as hashable tuples of (iso_date, weight);
    # rendered as JSON objects in output. Tuples keep the frozen record
    # hashable, which the pre-enrichment de-dup (dict.fromkeys) relies on.
    impact_by_day: tuple[tuple[str, int], ...] | None = None  # over statutory range
    impact_by_day_bridge: tuple[tuple[str, int], ...] | None = None  # over bridge range

    def is_tr_holiday(self) -> bool:
        """True for Turkish holidays (the records that get bridged/curved)."""
        return self.source in {"diyanet", "meb", "nager"} and self.country == "TR"

    def sort_key(self) -> tuple[date, str]:
        return (self.start_date, self.event.lower())

    def core_row(self) -> tuple[str, str, str, str, str, str, str, str]:
        """The eight headline fields as strings (no per-day JSON lists)."""
        return (
            self.event,
            self.start_date.isoformat(),
            self.end_date.isoformat(),
            self.city,
            self.nearest_airport or "",
            "" if self.impact_score is None else str(self.impact_score),
            self.bridge_start.isoformat() if self.bridge_start else "",
            self.bridge_end.isoformat() if self.bridge_end else "",
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["start_date"] = self.start_date.isoformat()
        data["end_date"] = self.end_date.isoformat()
        data["bridge_start"] = self.bridge_start.isoformat() if self.bridge_start else None
        data["bridge_end"] = self.bridge_end.isoformat() if self.bridge_end else None
        data["impact_by_day"] = dict(self.impact_by_day) if self.impact_by_day else None
        data["impact_by_day_bridge"] = (
            dict(self.impact_by_day_bridge) if self.impact_by_day_bridge else None
        )
        return data

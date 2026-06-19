"""Enrichment stage: nearest-airport mapping (IATA) and impact scoring.

Runs after collection/de-duplication. For events with venue coordinates it
attaches the nearest airport within a catchment radius; every record gets a
transparent 0-100 impact score so analysts can separate major from minor.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import date

from .dataset import load_airports
from .models import SpecialDate

DEFAULT_CATCHMENT_KM = 150.0
DEFAULT_MAX_EVENT_SPAN_DAYS = 30

# Base impact by category (0-100 before adjustments).
_CATEGORY_WEIGHT = {
    "religious_holiday": 90,
    "public_holiday": 70,
    "school_holiday": 55,
    "sports": 60,
    "concert": 55,
    "arts": 45,
    "film": 40,
    "event": 50,
}
_DEFAULT_WEIGHT = 45


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in kilometres."""
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def nearest_airport(lat: float, lon: float, catchment_km: float) -> tuple[str, float] | None:
    """Return ``(iata, distance_km)`` for the closest airport within range."""
    best = None
    for airport in load_airports():
        distance = haversine_km(lat, lon, airport["lat"], airport["lon"])
        if best is None or distance < best[1]:
            best = (airport["iata"], distance)
    if best is None or best[1] > catchment_km:
        return None
    return best


def _span_days(start: date, end: date) -> int:
    return (end - start).days + 1


def impact_score(record: SpecialDate, airport_distance_km: float | None) -> int:
    """A transparent 0-100 heuristic; calibrate the weights against history."""
    score = float(_CATEGORY_WEIGHT.get(record.category, _DEFAULT_WEIGHT))

    # Longer spans sustain demand (e.g. a 9-day bayram outranks a 3-day one).
    score += min(20, (_span_days(record.start_date, record.end_date) - 1) * 3)

    # Proximity to a major airport (events only).
    if airport_distance_km is not None:
        score += 15 if airport_distance_km <= 30 else 8
    elif record.lat is not None and record.lon is not None:
        # A located event with no airport within catchment matters a bit less.
        # (Records with incomplete coordinates are left neutral.)
        score -= 10

    return max(0, min(100, round(score)))


def drop_long_events(
    records: list[SpecialDate],
    max_event_span_days: int = DEFAULT_MAX_EVENT_SPAN_DAYS,
) -> list[SpecialDate]:
    """Drop over-long *events* — Ticketmaster season tickets and multi-month
    passes/exhibitions are listing artifacts, not demand spikes.

    Only ``ticketmaster`` records are affected; holidays and school breaks
    (which legitimately span weeks) are always kept. ``max_event_span_days <= 0``
    disables the filter.
    """
    if max_event_span_days <= 0:
        return list(records)
    kept: list[SpecialDate] = []
    for record in records:
        if record.source == "ticketmaster" and _span_days(record.start_date, record.end_date) > max_event_span_days:
            continue
        kept.append(record)
    return kept


def enrich(records: list[SpecialDate], catchment_km: float = DEFAULT_CATCHMENT_KM) -> list[SpecialDate]:
    """Return copies of ``records`` with airport + impact fields populated."""
    enriched: list[SpecialDate] = []
    for record in records:
        iata: str | None = None
        distance: float | None = None
        if record.lat is not None and record.lon is not None:
            match = nearest_airport(record.lat, record.lon, catchment_km)
            if match is not None:
                iata, distance = match[0], round(match[1], 1)

        enriched.append(
            dataclasses.replace(
                record,
                nearest_airport=iata,
                airport_distance_km=distance,
                impact_score=impact_score(record, distance),
            )
        )
    return enriched

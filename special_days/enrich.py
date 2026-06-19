"""Enrichment stage: nearest-airport mapping, scoring, bridges and curves.

Runs after collection/de-duplication. For events with venue coordinates it
attaches the nearest airport within a catchment radius. Every record then gets,
in order: a scalar impact score (via a pluggable scorer), a köprü bridge range
(TR holidays only) and two per-day weight curves (statutory + bridge).
"""

from __future__ import annotations

import dataclasses
import math
from concurrent.futures import ThreadPoolExecutor

from . import curve
from .bridge import compute_bridge
from .dataset import load_airports
from .models import SpecialDate
from .scoring import HeuristicScorer, Scorer

DEFAULT_CATCHMENT_KM = 150.0
DEFAULT_MAX_EVENT_SPAN_DAYS = 30


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


def _span_days(start, end) -> int:
    return (end - start).days + 1


def impact_score(record: SpecialDate, airport_distance_km: float | None) -> int:
    """Heuristic score for ``record`` (delegates to :class:`HeuristicScorer`).

    Kept for backwards compatibility; the scorer reads ``airport_distance_km``
    off the record, so it is set here before scoring.
    """
    return HeuristicScorer().score(
        dataclasses.replace(record, airport_distance_km=airport_distance_km)
    )


def drop_long_events(
    records: list[SpecialDate],
    max_event_span_days: int = DEFAULT_MAX_EVENT_SPAN_DAYS,
) -> list[SpecialDate]:
    """Drop over-long *events* — Ticketmaster season tickets and multi-month
    passes are listing artifacts, not demand spikes. Holidays/school breaks are
    always kept. ``max_event_span_days <= 0`` disables the filter.
    """
    if max_event_span_days <= 0:
        return list(records)
    kept: list[SpecialDate] = []
    for record in records:
        if record.source == "ticketmaster" and _span_days(record.start_date, record.end_date) > max_event_span_days:
            continue
        kept.append(record)
    return kept


def _map_airport(record: SpecialDate, catchment_km: float) -> SpecialDate:
    iata: str | None = None
    distance: float | None = None
    if record.lat is not None and record.lon is not None:
        match = nearest_airport(record.lat, record.lon, catchment_km)
        if match is not None:
            iata, distance = match[0], round(match[1], 1)
    return dataclasses.replace(record, nearest_airport=iata, airport_distance_km=distance)


def _score_all(records: list[SpecialDate], scorer: Scorer, concurrency: int) -> list[int]:
    """Score every record, preserving order.

    Runs the scorer concurrently when ``concurrency > 1`` — useful for the
    I/O-bound LLM scorers (one HTTP request per record). The heuristic path is
    unaffected (``concurrency <= 1`` runs plainly, no threads). The first error
    aborts the run.
    """
    if concurrency <= 1 or len(records) <= 1:
        return [scorer.score(record) for record in records]
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        return list(executor.map(scorer.score, records))  # ordered; re-raises on failure


def enrich(
    records: list[SpecialDate],
    catchment_km: float = DEFAULT_CATCHMENT_KM,
    scorer: Scorer | None = None,
    concurrency: int = 1,
) -> list[SpecialDate]:
    """Return copies of ``records`` with airport, score, bridge and curve fields.

    The scoring step (the costly one for LLM scorers) can run with up to
    ``concurrency`` parallel requests; airport mapping and bridge/curve building
    stay sequential (cheap CPU work).
    """
    if scorer is None:
        scorer = HeuristicScorer()

    # 1) airport mapping — must precede scoring (prompt + heuristic use it).
    mapped = [_map_airport(record, catchment_km) for record in records]

    # 2) scoring — the expensive step for LLM scorers; optionally concurrent.
    peaks = _score_all(mapped, scorer, concurrency)

    # 3) bridges + per-day curves.
    enriched: list[SpecialDate] = []
    for record, peak in zip(mapped, peaks):
        bridge_start, bridge_end = compute_bridge(record)
        enriched.append(
            dataclasses.replace(
                record,
                impact_score=peak,
                bridge_start=bridge_start,
                bridge_end=bridge_end,
                impact_by_day=curve.weights(record.start_date, record.end_date, peak),
                impact_by_day_bridge=curve.weights(bridge_start, bridge_end, peak),
            )
        )
    return enriched

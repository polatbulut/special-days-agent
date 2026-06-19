"""Pluggable impact scorers.

``HeuristicScorer`` (the default) is a transparent category/duration/proximity
heuristic. ``LLMScorer`` prompts an LLM gateway (OpenAI or vLLM) per record with
a scenario-specific prompt and parses a 0-100 score from the reply.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Callable, Protocol

from .gateways import make_gateway
from .models import SpecialDate

# Base impact by category, before duration/proximity adjustments.
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


def _span_days(start: date, end: date) -> int:
    return (end - start).days + 1


class Scorer(Protocol):
    def score(self, record: SpecialDate) -> int:
        ...


class HeuristicScorer:
    """Transparent 0-100 heuristic: category weight + duration + airport proximity."""

    def score(self, record: SpecialDate) -> int:
        score = float(_CATEGORY_WEIGHT.get(record.category, _DEFAULT_WEIGHT))

        # Longer spans sustain demand (a 9-day bayram outranks a 3-day one).
        score += min(20, (_span_days(record.start_date, record.end_date) - 1) * 3)

        distance = record.airport_distance_km
        if distance is not None:
            score += 15 if distance <= 30 else 8
        elif record.lat is not None and record.lon is not None:
            # A located event with no airport within catchment matters a bit less.
            score -= 10

        return max(0, min(100, round(score)))


# Scenario-specific prompts. The {placeholders} are filled from the record;
# avoid literal braces in the text.
_PROMPT_TR_HOLIDAY = (
    "Score 0-100 how strongly this Turkish holiday drives DOMESTIC and "
    "visiting-friends-and-relatives AIR-TRAVEL demand within Turkey. "
    "100 = a nationwide multi-day religious bayram with heavy travel; "
    "lower for minor or single-day observances.\n"
    "Holiday: {event}\nType: {category}\nDates: {start} to {end}\n"
    "Reply with ONLY an integer 0-100."
)
_PROMPT_INTL_HOLIDAY = (
    "Score 0-100 how strongly this public holiday in {country} drives "
    "INBOUND/OUTBOUND air-travel demand on routes to/from that market.\n"
    "Holiday: {event}\nType: {category}\nCountry: {country}\nDates: {start} to {end}\n"
    "Reply with ONLY an integer 0-100."
)
_PROMPT_EVENT = (
    "Score 0-100 the LOCALISED inbound air-travel demand this ticketed event "
    "creates for its host city (attendee + spectator travel).\n"
    "Event: {event}\nType: {category}\nCity: {city}, {country}\n"
    "Dates: {start} to {end}\nNearest airport: {airport}\n"
    "Reply with ONLY an integer 0-100."
)


class LLMScorer:
    """Scores a record by prompting an LLM gateway (a ``prompt -> reply`` callable)."""

    def __init__(self, call_model: Callable[[str], str]):
        self._model_fn = call_model

    def score(self, record: SpecialDate) -> int:
        return self._parse(self._model_fn(self._build_prompt(record)))

    def _scenario(self, record: SpecialDate) -> str:
        if record.is_tr_holiday():
            return "tr_holiday"
        if record.source == "nager":
            return "intl_holiday"
        return "event"

    def _build_prompt(self, record: SpecialDate) -> str:
        template = {
            "tr_holiday": _PROMPT_TR_HOLIDAY,
            "intl_holiday": _PROMPT_INTL_HOLIDAY,
            "event": _PROMPT_EVENT,
        }[self._scenario(record)]
        return template.format(
            event=record.event,
            category=record.category,
            country=record.country,
            city=record.city,
            start=record.start_date.isoformat(),
            end=record.end_date.isoformat(),
            airport=record.nearest_airport or "n/a",
        )

    @staticmethod
    def _parse(reply: str) -> int:
        text = (reply or "").strip().rstrip(".")
        if re.fullmatch(r"\d{1,3}", text):  # the requested "ONLY an integer" case
            return max(0, min(100, int(text)))
        # Preamble/extra text: take the LAST integer run (final-answer convention),
        # using \d+ so a year like 2026 isn't truncated to 202.
        numbers = re.findall(r"\d+", reply or "")
        if not numbers:
            raise ValueError(f"Could not parse an impact score from model reply: {reply!r}")
        return max(0, min(100, int(numbers[-1])))


def get_scorer(
    name: str,
    *,
    openai_api_key: str | None = None,
    vllm_base_url: str | None = None,
    vllm_api_key: str | None = None,
    model: str | None = None,
) -> Scorer:
    """Factory: ``heuristic`` (default), ``openai`` or ``vllm``.

    The LLM backends build the matching gateway (validating credentials) and
    wrap it in an :class:`LLMScorer`.
    """
    if name == "heuristic":
        return HeuristicScorer()
    if name in ("openai", "vllm"):
        gateway = make_gateway(
            name,
            openai_api_key=openai_api_key,
            vllm_base_url=vllm_base_url,
            vllm_api_key=vllm_api_key,
            model=model,
        )
        return LLMScorer(gateway)
    raise ValueError(f"Unknown impact scorer: {name!r}")

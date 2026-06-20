"""Pluggable impact scorers.

``HeuristicScorer`` (the default) is a transparent category/duration/proximity
heuristic. ``LLMScorer`` prompts an LLM gateway (OpenAI or vLLM) per record with
a per-source prompt and parses a structured result: an impact score (0-100,
framed as the effect on Turkish Airlines ticket sales) and — for events — a
predicted attendance.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Callable, NamedTuple, Protocol

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


class ScoreResult(NamedTuple):
    """A scorer's output: impact (0-100) and optional predicted attendance."""

    impact: int
    attendance: int | None = None


def _span_days(start: date, end: date) -> int:
    return (end - start).days + 1


class Scorer(Protocol):
    def score(self, record: SpecialDate) -> ScoreResult:
        ...


class HeuristicScorer:
    """Transparent 0-100 heuristic: category weight + duration + airport proximity.

    No attendance prediction — that requires an LLM scorer.
    """

    def score(self, record: SpecialDate) -> ScoreResult:
        score = float(_CATEGORY_WEIGHT.get(record.category, _DEFAULT_WEIGHT))

        # Longer spans sustain demand (a 9-day bayram outranks a 3-day one).
        score += min(20, (_span_days(record.start_date, record.end_date) - 1) * 3)

        distance = record.airport_distance_km
        if distance is not None:
            score += 15 if distance <= 30 else 8
        elif record.lat is not None and record.lon is not None:
            # A located event with no airport within catchment matters a bit less.
            score -= 10

        return ScoreResult(max(0, min(100, round(score))), None)


# --- Per-source prompts -----------------------------------------------------
# The impact is always framed as the effect on Turkish Airlines ticket sales.
# The JSON-shape instructions are plain (non-f) strings so the literal braces
# are safe.
_THY = "You are a Turkish Airlines (THY) revenue analyst."
_JSON_IMPACT_ONLY = 'Respond with ONLY JSON: {"impact": <integer 0-100>}'
_JSON_ATTENDANCE_IMPACT = (
    'Respond with ONLY JSON: {"attendance": <integer>, "impact": <integer 0-100>}'
)


def _dates(record: SpecialDate) -> str:
    return f"{record.start_date.isoformat()} to {record.end_date.isoformat()}"


def _prompt_nager(record: SpecialDate) -> str:
    return (
        f"{_THY} A public holiday in {record.country} is coming up. Estimate its "
        f"IMPACT (0-100) on Turkish Airlines TICKET SALES — how much it lifts THY "
        f"ticket demand (domestic, visiting-friends-and-relatives, and outbound "
        f"travel). 100 = a nationwide multi-day holiday driving heavy THY travel; "
        f"0 = negligible.\n"
        f"Holiday: {record.event}\nCountry: {record.country}\n"
        f"Type: {record.category}\nDates: {_dates(record)}\n"
    ) + _JSON_IMPACT_ONLY


def _prompt_diyanet(record: SpecialDate) -> str:
    return (
        f"{_THY} A Turkish religious holiday (bayram) is coming up. Bayrams trigger "
        f"the largest domestic and visiting-friends-and-relatives travel waves of "
        f"the year. Estimate its IMPACT (0-100) on Turkish Airlines TICKET SALES.\n"
        f"Holiday: {record.event}\nDates: {_dates(record)}\n"
    ) + _JSON_IMPACT_ONLY


def _prompt_meb(record: SpecialDate) -> str:
    return (
        f"{_THY} A Turkish school break (MEB calendar) is coming up, which "
        f"concentrates family leisure travel. Estimate its IMPACT (0-100) on "
        f"Turkish Airlines TICKET SALES.\n"
        f"Break: {record.event}\nDates: {_dates(record)}\n"
    ) + _JSON_IMPACT_ONLY


def _prompt_ticketmaster(record: SpecialDate) -> str:
    payload = json.dumps(record.raw or {}, ensure_ascii=False)
    return (
        f"{_THY} Below is the full API payload for a ticketed event. Predict:\n"
        f"1. attendance: the total expected attendance, as an integer.\n"
        f"2. impact: 0-100, how much this event lifts Turkish Airlines TICKET "
        f"SALES via inbound air travel to the host city "
        f"({record.city}, {record.country}; nearest airport "
        f"{record.nearest_airport or 'n/a'}). 100 = a huge draw pulling heavy "
        f"domestic/international air travel; 0 = negligible.\n"
        f"Event API payload (JSON):\n{payload}\n"
    ) + _JSON_ATTENDANCE_IMPACT


_PROMPT_BUILDERS = {
    "nager": _prompt_nager,
    "diyanet": _prompt_diyanet,
    "meb": _prompt_meb,
    "ticketmaster": _prompt_ticketmaster,
}


def _clamp_impact(value) -> int | None:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return None


def _coerce_attendance(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


class LLMScorer:
    """Scores a record by prompting an LLM gateway (a ``prompt -> reply`` callable)."""

    def __init__(self, call_model: Callable[[str], str]):
        self._model_fn = call_model

    def score(self, record: SpecialDate) -> ScoreResult:
        impact, attendance = self._parse(self._model_fn(self._build_prompt(record)))
        if record.source != "ticketmaster":
            attendance = None  # attendance is an event concept only
        return ScoreResult(impact, attendance)

    def _build_prompt(self, record: SpecialDate) -> str:
        return _PROMPT_BUILDERS.get(record.source, _prompt_ticketmaster)(record)

    @staticmethod
    def _parse(reply: str) -> tuple[int, int | None]:
        text = (reply or "").strip()
        if text.startswith("```"):  # strip a markdown code fence
            text = text.strip("`").strip()
            if text[:4].lower() == "json":
                text = text[4:].strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)  # first JSON object
        if match:
            try:
                obj = json.loads(match.group())
            except (json.JSONDecodeError, ValueError):
                obj = None
            if isinstance(obj, dict):
                impact = _clamp_impact(obj.get("impact"))
                if impact is not None:
                    return impact, _coerce_attendance(obj.get("attendance"))

        # Fallback: take the LAST integer run as the impact (final-answer
        # convention; \d+ so a year like 2026 isn't truncated to 202).
        numbers = re.findall(r"\d+", reply or "")
        if not numbers:
            raise ValueError(f"Could not parse a score from model reply: {reply!r}")
        return max(0, min(100, int(numbers[-1]))), None


def get_scorer(
    name: str,
    *,
    openai_api_key: str | None = None,
    vllm_base_url: str | None = None,
    vllm_api_key: str | None = None,
    azure_endpoint: str | None = None,
    azure_api_key: str | None = None,
    azure_api_version: str | None = None,
    model: str | None = None,
) -> Scorer:
    """Factory: ``heuristic`` (default), ``openai``, ``vllm`` or ``azure``.

    The LLM backends build the matching gateway (validating credentials) and
    wrap it in an :class:`LLMScorer`.
    """
    if name == "heuristic":
        return HeuristicScorer()
    if name in ("openai", "vllm", "azure"):
        gateway = make_gateway(
            name,
            openai_api_key=openai_api_key,
            vllm_base_url=vllm_base_url,
            vllm_api_key=vllm_api_key,
            azure_endpoint=azure_endpoint,
            azure_api_key=azure_api_key,
            azure_api_version=azure_api_version,
            model=model,
        )
        return LLMScorer(gateway)
    raise ValueError(f"Unknown impact scorer: {name!r}")

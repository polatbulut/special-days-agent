"""Command-line entry point for the special-days agents.

The agent collects a rolling forward window (default: the next 12 months) so a
weekly job always looks ahead.

Examples
--------
    # Next 12 months, both agents, as an Excel file (events need the key)
    python -m special_days --agent both --format xlsx -o out/special_days.xlsx

    # Turkey holidays only, next 6 months, to the terminal (no key needed)
    python -m special_days --agent turkey --source holidays --months 6

    # A specific window starting on a chosen date
    python -m special_days --start 2026-09-01 --months 12 --format csv
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date

from .agents import InternationalAgent, TurkeyAgent
from .config import (
    DEFAULT_INTERNATIONAL_COUNTRIES,
    get_openai_key,
    get_vllm_api_key,
    get_vllm_base_url,
    get_vllm_model,
    load_dotenv,
)
from .enrich import DEFAULT_CATCHMENT_KM, DEFAULT_MAX_EVENT_SPAN_DAYS, drop_long_events, enrich
from .models import SpecialDate
from .output import render
from .scoring import get_scorer
from .window import resolve_window

DEFAULT_MONTHS = 12


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return number


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return number


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a date in YYYY-MM-DD format")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="special_days",
        description="Discover special dates (holidays + events) for flight-occupancy forecasting.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--agent",
        choices=["turkey", "international", "both"],
        default="both",
        help="Which collector agent(s) to run (default: both).",
    )
    parser.add_argument(
        "--start",
        type=_iso_date,
        default=None,
        help="Window start date YYYY-MM-DD (default: today).",
    )
    parser.add_argument(
        "--months",
        type=_positive_int,
        default=DEFAULT_MONTHS,
        help=f"Window length in months from --start (default: {DEFAULT_MONTHS}).",
    )
    parser.add_argument(
        "--countries",
        default=None,
        help=(
            "Comma-separated ISO country codes for the international agent "
            f"(default: {','.join(DEFAULT_INTERNATIONAL_COUNTRIES)})."
        ),
    )
    parser.add_argument(
        "--source",
        choices=["holidays", "events", "all"],
        default="all",
        help="Which sources to pull (default: all).",
    )
    parser.add_argument(
        "--format",
        choices=["table", "csv", "json", "xlsx"],
        default="table",
        help="Output format (default: table). 'xlsx' writes an Excel file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            "Write to this file instead of stdout. For --format xlsx a file is "
            "always written (default: special_days_<start>_<end>.xlsx if omitted)."
        ),
    )
    parser.add_argument(
        "--catchment-km",
        type=float,
        default=DEFAULT_CATCHMENT_KM,
        help=f"Radius for nearest-airport mapping in km (default: {DEFAULT_CATCHMENT_KM:g}).",
    )
    parser.add_argument(
        "--max-event-span-days",
        type=_non_negative_int,
        default=DEFAULT_MAX_EVENT_SPAN_DAYS,
        help=(
            "Drop events spanning more than this many days as noise "
            f"(season tickets); 0 disables (default: {DEFAULT_MAX_EVENT_SPAN_DAYS})."
        ),
    )
    parser.add_argument(
        "--impact-scorer",
        choices=["heuristic", "openai", "vllm"],
        default="heuristic",
        help=(
            "How to score impact (default: heuristic). 'openai' uses OPENAI_API_KEY "
            "(model gpt-5-mini); 'vllm' uses VLLM_BASE_URL + VLLM_MODEL."
        ),
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="Override the LLM model (default: gpt-5-mini for openai; VLLM_MODEL for vllm).",
    )
    parser.add_argument(
        "--concurrency",
        type=_positive_int,
        default=None,
        help="Parallel LLM scoring requests (default: 8 for openai/vllm, 1 for heuristic).",
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        default=None,
        help="Cap the number of rows printed (after sorting by date).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log collection progress and skipped sources to stderr.",
    )
    return parser


def _agents_for(args: argparse.Namespace):
    countries = (
        [c.strip() for c in args.countries.split(",") if c.strip()]
        if args.countries
        else None
    )
    if args.agent == "turkey":
        return [TurkeyAgent()]
    if args.agent == "international":
        return [InternationalAgent(countries=countries)]
    return [TurkeyAgent(), InternationalAgent(countries=countries)]


def collect(args: argparse.Namespace, start: date, end: date) -> list[SpecialDate]:
    """Collect and de-duplicate raw special dates within ``[start, end]``."""
    include_holidays = args.source in ("holidays", "all")
    include_events = args.source in ("events", "all")

    results: list[SpecialDate] = []
    for agent in _agents_for(args):
        results.extend(
            agent.collect(
                start,
                end,
                include_holidays=include_holidays,
                include_events=include_events,
            )
        )

    # The Turkey and International agents can overlap (e.g. TR passed in
    # --countries while --agent both), so de-duplicate. SpecialDate is
    # frozen/hashable, so dict.fromkeys preserves first-seen order.
    return list(dict.fromkeys(results))


def _xlsx_path(args: argparse.Namespace, start: date, end: date) -> str:
    if args.output:
        return args.output if args.output.lower().endswith(".xlsx") else f"{args.output}.xlsx"
    return f"special_days_{start.isoformat()}_{end.isoformat()}.xlsx"


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()

    model = args.llm_model
    if args.impact_scorer == "vllm" and not model:
        model = get_vllm_model()
    try:
        scorer = get_scorer(
            args.impact_scorer,
            openai_api_key=get_openai_key(),
            vllm_base_url=get_vllm_base_url(),
            vllm_api_key=get_vllm_api_key(),
            model=model,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    start, end = resolve_window(args.start, args.months)
    logging.getLogger(__name__).info("Collecting window %s -> %s", start, end)

    concurrency = args.concurrency
    if concurrency is None:
        concurrency = 1 if args.impact_scorer == "heuristic" else 8

    rows = collect(args, start, end)
    rows = drop_long_events(rows, args.max_event_span_days)
    rows = enrich(rows, catchment_km=args.catchment_km, scorer=scorer, concurrency=concurrency)
    rows.sort(key=SpecialDate.sort_key)
    if args.limit is not None:
        rows = rows[: args.limit]

    if args.format == "xlsx":
        from .xlsx_writer import write_xlsx

        path = _xlsx_path(args, start, end)
        _ensure_parent(path)
        write_xlsx(rows, path)
        print(f"Wrote {len(rows)} special date(s) to {path}")
        return 0

    text = render(rows, args.format)
    if args.output:
        _ensure_parent(args.output)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(f"Wrote {len(rows)} special date(s) to {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Command-line entry point for the special-days agents.

Examples
--------
    # Turkey holidays for 2026 (no API key needed)
    python -m special_days --agent turkey --year 2026 --source holidays

    # Everything both agents can find (events need TICKETMASTER_API_KEY)
    python -m special_days --agent both --year 2026

    # International holidays for specific markets, as CSV
    python -m special_days --agent international --countries DE,GB,AE \\
        --source holidays --format csv
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date

from .agents import InternationalAgent, TurkeyAgent
from .config import DEFAULT_INTERNATIONAL_COUNTRIES, load_dotenv
from .models import SpecialDate
from .output import render

DEFAULT_YEAR = date(2026, 1, 1).year  # avoids importing clock state into help text


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return number


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
        "--year",
        type=int,
        default=DEFAULT_YEAR,
        help=f"Calendar year to collect (default: {DEFAULT_YEAR}).",
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
            "always written (default: special_days_<year>.xlsx if omitted)."
        ),
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


def collect(args: argparse.Namespace) -> list[SpecialDate]:
    include_holidays = args.source in ("holidays", "all")
    include_events = args.source in ("events", "all")

    results: list[SpecialDate] = []
    for agent in _agents_for(args):
        results.extend(
            agent.collect(
                args.year,
                include_holidays=include_holidays,
                include_events=include_events,
            )
        )

    # The Turkey and International agents can overlap (e.g. TR passed in
    # --countries while --agent both), so de-duplicate before sorting.
    # SpecialDate is frozen/hashable, so dict.fromkeys preserves first-seen order.
    results = list(dict.fromkeys(results))
    results.sort(key=SpecialDate.sort_key)
    if args.limit is not None:
        results = results[: args.limit]
    return results


def _xlsx_path(args: argparse.Namespace) -> str:
    if args.output:
        return args.output if args.output.lower().endswith(".xlsx") else f"{args.output}.xlsx"
    return f"special_days_{args.year}.xlsx"


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

    rows = collect(args)

    if args.format == "xlsx":
        from .xlsx_writer import write_xlsx

        path = _xlsx_path(args)
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

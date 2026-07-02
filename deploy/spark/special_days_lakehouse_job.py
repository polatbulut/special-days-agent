"""Spark batch job: scrape -> enrich -> write the special_events lakehouse tables.

Runs entirely on the THY Spark nonprod cluster (it has internet egress). It
collects the next N months of special dates, enriches them with the **heuristic**
scorer (no live LLM calls in a scheduled job), and writes two Hive/Parquet tables
under ``/lakehouse/special_events``::

    special_events.special_days_raw       span grain (one row per special date)
    special_events.special_days_features  day x airport feature grain

Run on the cluster after ``git pull`` (a JupyterHub terminal or an edge node)::

    spark-submit deploy/spark/special_days_lakehouse_job.py --months 12

Configuration (flag, or the matching env var):

    --database / SPECIAL_DAYS_DB         (default: special_events)
    --location / SPECIAL_DAYS_LOCATION   (default: /lakehouse/special_events)
    --months   / SPECIAL_DAYS_MONTHS     (default: 12)
    --start    YYYY-MM-DD                 (default: today)
    --countries CSV ISO codes for the international agent (default: built-in list)

Source API keys (Ticketmaster / API-Football) and EVENTSEYE_ENABLED are read from
the environment / a ``.env`` file if present; missing ones are skipped cleanly,
so a no-key run still lands all the holiday sources.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date

# Make the repo importable when launched as `spark-submit deploy/spark/<this>.py`:
# spark-submit only puts the script's own directory on sys.path, not the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from pyspark.sql import SparkSession  # noqa: E402  (after the sys.path tweak)

from special_days.agents import InternationalAgent, TurkeyAgent  # noqa: E402
from special_days.config import load_dotenv  # noqa: E402
from special_days.enrich import (  # noqa: E402
    DEFAULT_CATCHMENT_KM,
    DEFAULT_MAX_EVENT_SPAN_DAYS,
    drop_long_events,
    enrich,
)
from special_days.models import SpecialDate  # noqa: E402
from special_days.scoring import HeuristicScorer  # noqa: E402
from special_days.sinks import lakehouse  # noqa: E402
from special_days.window import resolve_window  # noqa: E402

logger = logging.getLogger("special_days.lakehouse_job")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Write the special-days feed to the lakehouse.")
    p.add_argument("--database", default=os.environ.get("SPECIAL_DAYS_DB", lakehouse.DEFAULT_DATABASE))
    p.add_argument("--location", default=os.environ.get("SPECIAL_DAYS_LOCATION", lakehouse.DEFAULT_LOCATION))
    p.add_argument("--months", type=int, default=int(os.environ.get("SPECIAL_DAYS_MONTHS", "12")))
    p.add_argument("--start", default=None, help="Window start YYYY-MM-DD (default: today).")
    p.add_argument("--countries", default=None, help="CSV ISO codes for the international agent.")
    p.add_argument("--catchment-km", type=float, default=DEFAULT_CATCHMENT_KM)
    p.add_argument("--max-event-span-days", type=int, default=DEFAULT_MAX_EVENT_SPAN_DAYS)
    return p.parse_args(argv)


def collect_records(start: date, end: date, countries: list[str] | None) -> list[SpecialDate]:
    """Collect both agents over ``[start, end]`` (all sources) and de-duplicate."""
    records: list[SpecialDate] = []
    for agent in (TurkeyAgent(), InternationalAgent(countries=countries)):
        records.extend(
            agent.collect(start, end, include_holidays=True, include_events=True)
        )
    # SpecialDate is frozen/hashable; dict.fromkeys de-dups, preserving order.
    return list(dict.fromkeys(records))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv()  # optional on the cluster: picks up source API keys if present

    countries = (
        [c.strip() for c in args.countries.split(",") if c.strip()]
        if args.countries
        else None
    )
    start_date = date.fromisoformat(args.start) if args.start else None
    start, end = resolve_window(start_date, args.months)
    logger.info("Collecting window %s -> %s", start, end)

    records = collect_records(start, end, countries)
    records = drop_long_events(records, args.max_event_span_days)
    records = enrich(records, catchment_km=args.catchment_km, scorer=HeuristicScorer())
    records.sort(key=SpecialDate.sort_key)
    logger.info("Collected %d special date(s)", len(records))

    spark = (
        SparkSession.builder
        .appName("special-days-lakehouse")
        .enableHiveSupport()
        .getOrCreate()
    )
    try:
        run_id = lakehouse.write(
            records, spark=spark, database=args.database, location=args.location
        )
    finally:
        spark.stop()

    print(
        f"Wrote {len(records)} special date(s) -> "
        f"{args.database}.{lakehouse.DEFAULT_RAW_TABLE} + "
        f"{args.database}.{lakehouse.DEFAULT_FEATURE_TABLE} (run_id={run_id})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

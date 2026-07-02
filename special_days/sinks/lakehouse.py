"""Write the collected feed to the THY Spark lakehouse (Hive / Parquet).

The whole pipeline runs on the Spark nonprod cluster (it has internet egress)::

    scrape -> enrich -> build two Spark DataFrames -> two Hive/Parquet tables

Two tables are written under one lakehouse location (default
``/lakehouse/special_events``, database ``special_events``):

``special_days_raw`` — **span grain**, one row per :class:`SpecialDate`, with the
per-day impact curves kept as JSON strings. The audit / reprocess layer.

``special_days_features`` — **day x airport feature grain**. The statutory and
bridge per-day curves are merged (per-day max) and exploded to one row per
``(event_date, country, airport)``. National holidays have no single airport, so
they are kept with ``airport = NULL`` (country populated) rather than dropped —
they are nationwide demand and the biggest signal in the feed.

Design: the pure-Python row builders (:func:`record_key`, :func:`to_raw_rows`,
:func:`explode_features`) hold *all* the business logic and are unit-tested
without Spark. ``pyspark`` is imported lazily inside :func:`write` and
:func:`build_schemas`, so importing this module on a laptop with no Spark
installed is fine.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from ..models import SpecialDate

DEFAULT_DATABASE = "special_events"
DEFAULT_LOCATION = "/lakehouse/special_events"
DEFAULT_RAW_TABLE = "special_days_raw"
DEFAULT_FEATURE_TABLE = "special_days_features"

# Column order shared by the row builders and the Spark schemas. The row tuples
# are positional, so these orders must stay in lock-step with ``build_schemas``.
RAW_COLUMNS = (
    "record_key", "event", "start_date", "end_date", "city", "category",
    "country", "source", "lat", "lon", "nearest_airport", "airport_distance_km",
    "impact_score", "predicted_attendance", "bridge_start", "bridge_end",
    "impact_by_day", "impact_by_day_bridge", "run_id", "load_ts",
)
FEATURE_COLUMNS = (
    "event_date", "country", "airport", "impact", "predicted_attendance",
    "sources", "n_events", "feature_timestamp", "run_id",
)

_ONE_DAY = timedelta(days=1)


def record_key(row: SpecialDate) -> str:
    """Deterministic business key: SHA-1 hex of the collection-time identity.

    Identity = ``(source, event, start, end, city, country, category, lat, lon)``.
    ``category`` and ``lat``/``lon`` are included so two genuinely-distinct rows
    that survive the in-memory de-dup don't collapse to one key. Enrichment-only
    fields (impact_score, nearest_airport, the curves) are excluded so a re-run
    maps the same special date to the same key (idempotent overwrite).
    """
    def _coord(value: float | None) -> str:
        return "" if value is None else repr(value)

    basis = "|".join((
        row.source,
        row.event,
        row.start_date.isoformat(),
        row.end_date.isoformat(),
        row.city,
        row.country,
        row.category,
        _coord(row.lat),
        _coord(row.lon),
    ))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _curve_json(curve: tuple[tuple[str, int], ...] | None) -> str | None:
    """Render a per-day weight curve as a JSON object string, or ``None``."""
    return json.dumps(dict(curve), ensure_ascii=False) if curve else None


def _dedup_by_key(records: Iterable[SpecialDate]) -> list[SpecialDate]:
    """Collapse to one record per :func:`record_key` (last wins, order preserved).

    Distinct ``SpecialDate`` rows can share a key when they differ only on
    enrichment fields (outside the key basis). Deduping here keeps the raw table
    one-row-per-key and stops the feature explosion from double-counting one
    special date's attendance into the same day x airport cell.
    """
    by_key: "OrderedDict[str, SpecialDate]" = OrderedDict()
    for row in records:
        by_key[record_key(row)] = row
    return list(by_key.values())


def to_raw_rows(records: Iterable[SpecialDate], run_id: str, load_ts: datetime) -> list[tuple]:
    """Span-grain rows (one tuple per special date), aligned to ``RAW_COLUMNS``.

    Dates are passed as native ``datetime.date`` objects (Spark maps them to
    DateType); the per-day curves become JSON strings; ``None`` stays NULL.
    """
    rows: list[tuple] = []
    for r in _dedup_by_key(records):
        rows.append((
            record_key(r),
            r.event,
            r.start_date,
            r.end_date,
            r.city,
            r.category,
            r.country,
            r.source,
            r.lat,
            r.lon,
            r.nearest_airport,
            r.airport_distance_km,
            r.impact_score,
            r.predicted_attendance,
            r.bridge_start,
            r.bridge_end,
            _curve_json(r.impact_by_day),
            _curve_json(r.impact_by_day_bridge),
            run_id,
            load_ts,
        ))
    return rows


def _effective_curve(record: SpecialDate) -> dict[str, int]:
    """Merge the statutory and bridge per-day curves by **per-day max**.

    After enrichment both curves are present; the bridge curve covers the same or
    a wider date range (TR holidays). Taking the max per ISO date keeps every
    bridge day while never under-stating a statutory day (whose weight can differ
    because the Linear-V is computed over a different span length). If a record
    has no curves (un-enriched input), fall back to a flat ``impact_score`` over
    ``[start_date, end_date]`` so the record still appears in the feature table.
    """
    merged: dict[str, int] = {}
    for curve in (record.impact_by_day, record.impact_by_day_bridge):
        if not curve:
            continue
        for iso, weight in curve:
            if iso not in merged or weight > merged[iso]:
                merged[iso] = weight
    if not merged:
        peak = record.impact_score or 0
        cursor = record.start_date
        while cursor <= record.end_date:
            merged[cursor.isoformat()] = peak
            cursor += _ONE_DAY
    return merged


def explode_features(records: Iterable[SpecialDate], run_id: str, load_ts: datetime) -> list[tuple]:
    """Day x airport feature rows, aligned to ``FEATURE_COLUMNS``.

    Each record's effective per-day curve is exploded to one entry per calendar
    day, keyed by ``(event_date, country, airport)`` (airport may be ``None`` for
    nationwide holidays). Cells are aggregated across all records:

    * ``impact``               = max per-day weight (peak demand that day there)
    * ``predicted_attendance`` = sum of contributing events' attendance
      (``None`` when no contributor has an attendance figure — e.g. holidays)
    * ``sources``              = sorted distinct source names, comma-joined
    * ``n_events``             = number of distinct special dates contributing
    """
    cells: "OrderedDict[tuple, dict]" = OrderedDict()
    for r in _dedup_by_key(records):
        curve = _effective_curve(r)
        for iso, weight in curve.items():
            cell_key = (date.fromisoformat(iso), r.country, r.nearest_airport)
            agg = cells.get(cell_key)
            if agg is None:
                agg = {"impact": weight, "attendance": None, "sources": set(), "n": 0}
                cells[cell_key] = agg
            if weight > agg["impact"]:
                agg["impact"] = weight
            if r.predicted_attendance is not None:
                agg["attendance"] = (agg["attendance"] or 0) + r.predicted_attendance
            agg["sources"].add(r.source)
            agg["n"] += 1

    rows: list[tuple] = []
    for (event_date, country, airport), agg in cells.items():
        rows.append((
            event_date,
            country,
            airport,
            int(agg["impact"]),
            agg["attendance"],
            ",".join(sorted(agg["sources"])),
            agg["n"],
            load_ts,
            run_id,
        ))
    return rows


def build_schemas():
    """Return ``(raw_schema, feature_schema)`` as Spark ``StructType``s.

    Imported lazily so the module loads without pyspark. Field order matches
    ``RAW_COLUMNS`` / ``FEATURE_COLUMNS`` and the positional row tuples.
    """
    from pyspark.sql import types as T

    raw = T.StructType([
        T.StructField("record_key", T.StringType(), False),
        T.StructField("event", T.StringType(), False),
        T.StructField("start_date", T.DateType(), False),
        T.StructField("end_date", T.DateType(), False),
        T.StructField("city", T.StringType(), True),
        T.StructField("category", T.StringType(), True),
        T.StructField("country", T.StringType(), True),
        T.StructField("source", T.StringType(), True),
        T.StructField("lat", T.DoubleType(), True),
        T.StructField("lon", T.DoubleType(), True),
        T.StructField("nearest_airport", T.StringType(), True),
        T.StructField("airport_distance_km", T.DoubleType(), True),
        T.StructField("impact_score", T.IntegerType(), True),
        T.StructField("predicted_attendance", T.LongType(), True),
        T.StructField("bridge_start", T.DateType(), True),
        T.StructField("bridge_end", T.DateType(), True),
        T.StructField("impact_by_day", T.StringType(), True),
        T.StructField("impact_by_day_bridge", T.StringType(), True),
        T.StructField("run_id", T.StringType(), True),
        T.StructField("load_ts", T.TimestampType(), True),
    ])
    feature = T.StructType([
        T.StructField("event_date", T.DateType(), False),
        T.StructField("country", T.StringType(), True),
        T.StructField("airport", T.StringType(), True),
        T.StructField("impact", T.IntegerType(), True),
        T.StructField("predicted_attendance", T.LongType(), True),
        T.StructField("sources", T.StringType(), True),
        T.StructField("n_events", T.IntegerType(), True),
        T.StructField("feature_timestamp", T.TimestampType(), True),
        T.StructField("run_id", T.StringType(), True),
    ])
    return raw, feature


def _save(df, database: str, table: str, location: str, mode: str) -> None:
    """Write ``df`` as an external Parquet table ``database.table``.

    The explicit ``path`` option makes the table external (data files persist
    under ``location/table`` independent of the metastore). ``coalesce(1)`` keeps
    the tiny feed to a single Parquet file instead of many small ones.
    """
    (
        df.coalesce(1)
        .write.mode(mode)
        .format("parquet")
        .option("path", f"{location.rstrip('/')}/{table}")
        .saveAsTable(f"{database}.{table}")
    )


def write(
    records: Iterable[SpecialDate],
    *,
    spark,
    database: str = DEFAULT_DATABASE,
    location: str = DEFAULT_LOCATION,
    raw_table: str = DEFAULT_RAW_TABLE,
    feature_table: str = DEFAULT_FEATURE_TABLE,
    mode: str = "overwrite",
    run_id: str | None = None,
    load_ts: datetime | None = None,
) -> str:
    """Write the raw span table and the day x airport feature table; return run id.

    ``spark`` is an active ``SparkSession`` (with Hive support). ``run_id`` /
    ``load_ts`` default to a fresh UUID and the current UTC time and are stamped
    on every row of this run for point-in-time freshness. ``mode='overwrite'``
    does a full daily refresh — idempotent and trivial at this volume.

    Everything this writes — both table directories *and* the database's own
    directory — lands under ``location``. The dev service account is granted
    write only under the ``special_events`` prefix (read-only over the rest of the
    lakehouse), so the database is created with an explicit ``LOCATION`` inside
    that prefix rather than the default Hive warehouse (which the account can't
    write to). ``IF NOT EXISTS`` makes the create a no-op if the storage team
    pre-provisioned the database.
    """
    records = list(records)
    run_id = run_id or uuid.uuid4().hex
    load_ts = load_ts or datetime.now(timezone.utc)

    raw_schema, feature_schema = build_schemas()
    raw_df = spark.createDataFrame(to_raw_rows(records, run_id, load_ts), schema=raw_schema)
    feature_df = spark.createDataFrame(
        explode_features(records, run_id, load_ts), schema=feature_schema
    )

    spark.sql(f"CREATE DATABASE IF NOT EXISTS {database} LOCATION '{location}'")
    _save(raw_df, database, raw_table, location, mode)
    _save(feature_df, database, feature_table, location, mode)
    return run_id

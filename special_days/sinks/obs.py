"""Write the collected feed to Huawei OBS as Parquet — no Spark.

Builds the rows in memory, encodes them as Parquet with ``pyarrow``, and uploads
two objects to OBS with the OBS SDK (``esdk-obs-python``); consumers read them by
path. Runs anywhere with network access to OBS (a terminal, a container, cron)::

    <location>/special_days_raw/data.parquet       span grain (one row per date)
    <location>/special_days_features/data.parquet   day x airport feature grain

National holidays have no single airport, so feature rows keep ``airport = NULL``
(country populated) rather than being dropped. Each object is a single fixed key,
overwritten each run (idempotent). Credentials come from the environment (the
``OBS_*`` vars in ``.env.example``), never hardcoded; ``pyarrow`` and the OBS SDK
are imported lazily, so the pure-Python row builders work without either.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable

from ..models import SpecialDate

DEFAULT_LOCATION = "obs://lakehouse-dev/special_events"
DEFAULT_RAW_TABLE = "special_days_raw"
DEFAULT_FEATURE_TABLE = "special_days_features"
DEFAULT_OBJECT_NAME = "data.parquet"

# Column order shared by the row builders and the Parquet schemas. The row tuples
# are positional, so these orders must stay in lock-step with ``_arrow_schemas``.
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
    enrichment fields (outside the key basis). Deduping here keeps the raw dataset
    one-row-per-key and stops the feature explosion from double-counting one
    special date's attendance into the same day x airport cell.
    """
    by_key: "OrderedDict[str, SpecialDate]" = OrderedDict()
    for row in records:
        by_key[record_key(row)] = row
    return list(by_key.values())


def to_raw_rows(records: Iterable[SpecialDate], run_id: str, load_ts: datetime) -> list[tuple]:
    """Span-grain rows (one tuple per special date), aligned to ``RAW_COLUMNS``.

    Dates are native ``datetime.date`` objects; the per-day curves become JSON
    strings; ``None`` stays NULL.
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
    ``[start_date, end_date]`` so the record still appears in the feature dataset.
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


def parse_obs_uri(uri: str) -> tuple[str, str]:
    """Split ``obs://bucket/prefix/...`` into ``(bucket, prefix)`` (prefix may be '')."""
    rest = uri.partition("://")[2] if "://" in uri else uri
    rest = rest.strip("/")
    bucket, _, prefix = rest.partition("/")
    return bucket, prefix


def _arrow_schemas():
    """Return ``(raw_schema, feature_schema)`` as pyarrow schemas (lazy import).

    Field order matches ``RAW_COLUMNS`` / ``FEATURE_COLUMNS`` and the row tuples.
    """
    import pyarrow as pa

    raw = pa.schema([
        ("record_key", pa.string()),
        ("event", pa.string()),
        ("start_date", pa.date32()),
        ("end_date", pa.date32()),
        ("city", pa.string()),
        ("category", pa.string()),
        ("country", pa.string()),
        ("source", pa.string()),
        ("lat", pa.float64()),
        ("lon", pa.float64()),
        ("nearest_airport", pa.string()),
        ("airport_distance_km", pa.float64()),
        ("impact_score", pa.int32()),
        ("predicted_attendance", pa.int64()),
        ("bridge_start", pa.date32()),
        ("bridge_end", pa.date32()),
        ("impact_by_day", pa.string()),
        ("impact_by_day_bridge", pa.string()),
        ("run_id", pa.string()),
        ("load_ts", pa.timestamp("us", tz="UTC")),
    ])
    feature = pa.schema([
        ("event_date", pa.date32()),
        ("country", pa.string()),
        ("airport", pa.string()),
        ("impact", pa.int32()),
        ("predicted_attendance", pa.int64()),
        ("sources", pa.string()),
        ("n_events", pa.int32()),
        ("feature_timestamp", pa.timestamp("us", tz="UTC")),
        ("run_id", pa.string()),
    ])
    return raw, feature


def _parquet_bytes(rows: list[tuple], schema) -> bytes:
    """Encode positional ``rows`` as a Parquet file (bytes) matching ``schema``."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    if rows:
        columns = list(zip(*rows))
    else:
        columns = [() for _ in range(len(schema))]
    arrays = [pa.array(list(col), type=field.type) for col, field in zip(columns, schema)]
    table = pa.Table.from_arrays(arrays, schema=schema)
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def _object_key(prefix: str, table: str, object_name: str) -> str:
    """Join a non-empty ``prefix``, ``table`` and ``object_name`` into an OBS key."""
    return "/".join(part for part in (prefix, table, object_name) if part)


def _obs_client(endpoint: str, access_key: str, secret_key: str):
    """Construct an OBS SDK client; prepend ``https://`` if the endpoint has no scheme."""
    from obs import ObsClient  # lazy: only needed when actually uploading

    server = endpoint if "://" in endpoint else f"https://{endpoint}"
    return ObsClient(access_key_id=access_key, secret_access_key=secret_key, server=server)


def _put(client, bucket: str, key: str, content: bytes) -> None:
    """Upload ``content`` to ``bucket/key`` and raise on a non-2xx OBS response."""
    resp = client.putContent(bucket, key, content=content)
    status = getattr(resp, "status", None)
    if status is not None and status >= 300:
        raise RuntimeError(
            f"OBS putContent failed for {bucket}/{key}: status={status} "
            f"code={getattr(resp, 'errorCode', None)} message={getattr(resp, 'errorMessage', None)}"
        )


def write(
    records: Iterable[SpecialDate],
    *,
    endpoint: str,
    access_key: str,
    secret_key: str,
    location: str = DEFAULT_LOCATION,
    raw_table: str = DEFAULT_RAW_TABLE,
    feature_table: str = DEFAULT_FEATURE_TABLE,
    object_name: str = DEFAULT_OBJECT_NAME,
    run_id: str | None = None,
    load_ts: datetime | None = None,
    client: object | None = None,
) -> str:
    """Encode the two datasets as Parquet and upload them to OBS; return the run id.

    ``location`` is an ``obs://bucket/prefix`` URI. Each dataset is a single object
    at a fixed key (``<prefix>/<table>/<object_name>``), overwritten on re-run so
    the write is idempotent. ``run_id`` / ``load_ts`` default to a fresh UUID and
    the current UTC time and are stamped on every row for point-in-time freshness.
    ``client`` (an object exposing ``putContent`` / ``close``) is injectable so
    tests run without the OBS SDK or a live bucket.
    """
    records = list(records)
    run_id = run_id or uuid.uuid4().hex
    load_ts = load_ts or datetime.now(timezone.utc)
    bucket, prefix = parse_obs_uri(location)

    raw_schema, feature_schema = _arrow_schemas()
    raw_bytes = _parquet_bytes(to_raw_rows(records, run_id, load_ts), raw_schema)
    feature_bytes = _parquet_bytes(explode_features(records, run_id, load_ts), feature_schema)

    owns_client = client is None
    if owns_client:
        client = _obs_client(endpoint, access_key, secret_key)
    try:
        _put(client, bucket, _object_key(prefix, raw_table, object_name), raw_bytes)
        _put(client, bucket, _object_key(prefix, feature_table, object_name), feature_bytes)
    finally:
        if owns_client:
            client.close()
    return run_id

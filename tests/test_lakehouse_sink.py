"""Pure-Python tests for the lakehouse sink row builders (no Spark required)."""

import json
import unittest
from datetime import date, datetime, timezone

from special_days.models import SpecialDate
from special_days.sinks import lakehouse

TS = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)


def _rec(**kw) -> SpecialDate:
    base = dict(
        event="X",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        city="Istanbul",
        category="public_holiday",
        country="TR",
        source="nager",
    )
    base.update(kw)
    return SpecialDate(**base)


def _features_by_cell(rows):
    """Map (event_date, country, airport) -> dict(column -> value)."""
    out = {}
    for row in rows:
        d = dict(zip(lakehouse.FEATURE_COLUMNS, row))
        out[(d["event_date"], d["country"], d["airport"])] = d
    return out


class RecordKeyTest(unittest.TestCase):
    def test_deterministic_for_same_identity(self):
        self.assertEqual(lakehouse.record_key(_rec()), lakehouse.record_key(_rec()))

    def test_excludes_enrichment_fields(self):
        # Enrichment-only fields must not change the key (idempotent re-runs).
        bare = _rec()
        enriched = _rec(
            impact_score=90,
            nearest_airport="IST",
            airport_distance_km=3.2,
            predicted_attendance=1000,
            impact_by_day=(("2026-01-01", 90),),
        )
        self.assertEqual(lakehouse.record_key(bare), lakehouse.record_key(enriched))

    def test_distinguishes_source_and_coords(self):
        self.assertNotEqual(
            lakehouse.record_key(_rec(source="nager")),
            lakehouse.record_key(_rec(source="diyanet")),
        )
        self.assertNotEqual(
            lakehouse.record_key(_rec(lat=41.0, lon=29.0)),
            lakehouse.record_key(_rec(lat=39.9, lon=32.8)),
        )


class RawRowsTest(unittest.TestCase):
    def test_one_tuple_per_record_aligned_to_columns(self):
        rows = lakehouse.to_raw_rows([_rec(event="A"), _rec(event="B")], "run", TS)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row), len(lakehouse.RAW_COLUMNS))

    def test_dedup_by_key_last_wins(self):
        # Same identity (key), different enrichment -> a single raw row, last wins.
        a = _rec(impact_score=10)
        b = _rec(impact_score=90)
        rows = lakehouse.to_raw_rows([a, b], "run", TS)
        self.assertEqual(len(rows), 1)
        d = dict(zip(lakehouse.RAW_COLUMNS, rows[0]))
        self.assertEqual(d["impact_score"], 90)

    def test_dates_passed_through_and_curves_jsonified(self):
        rec = _rec(
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 2),
            impact_by_day=(("2026-05-01", 70), ("2026-05-02", 50)),
            impact_by_day_bridge=None,
        )
        d = dict(zip(lakehouse.RAW_COLUMNS, lakehouse.to_raw_rows([rec], "run", TS)[0]))
        self.assertEqual(d["start_date"], date(2026, 5, 1))      # native date, not iso str
        self.assertEqual(d["end_date"], date(2026, 5, 2))
        self.assertEqual(json.loads(d["impact_by_day"]), {"2026-05-01": 70, "2026-05-02": 50})
        self.assertIsNone(d["impact_by_day_bridge"])             # empty curve -> NULL
        self.assertEqual(d["run_id"], "run")
        self.assertEqual(d["load_ts"], TS)


class ExplodeFeaturesTest(unittest.TestCase):
    def test_event_explodes_to_one_row_per_day_at_airport(self):
        ev = _rec(
            event="Concert", category="concert", source="ticketmaster",
            lat=41.0, lon=29.0, nearest_airport="IST",
            start_date=date(2026, 5, 1), end_date=date(2026, 5, 3),
            impact_score=40, predicted_attendance=1000,
            impact_by_day=(("2026-05-01", 40), ("2026-05-02", 20), ("2026-05-03", 40)),
            impact_by_day_bridge=(("2026-05-01", 40), ("2026-05-02", 20), ("2026-05-03", 40)),
        )
        cells = _features_by_cell(lakehouse.explode_features([ev], "run", TS))
        self.assertEqual(len(cells), 3)
        mid = cells[(date(2026, 5, 2), "TR", "IST")]
        self.assertEqual(mid["impact"], 20)
        self.assertEqual(mid["predicted_attendance"], 1000)
        self.assertEqual(mid["sources"], "ticketmaster")
        self.assertEqual(mid["n_events"], 1)
        self.assertEqual(mid["feature_timestamp"], TS)

    def test_national_holiday_kept_with_null_airport(self):
        hol = _rec(
            event="Bayram", category="religious_holiday", source="diyanet",
            nearest_airport=None,
            start_date=date(2026, 5, 2), end_date=date(2026, 5, 2),
            impact_score=99,
            impact_by_day=(("2026-05-02", 99),),
            impact_by_day_bridge=(("2026-05-02", 99),),
        )
        cells = _features_by_cell(lakehouse.explode_features([hol], "run", TS))
        self.assertIn((date(2026, 5, 2), "TR", None), cells)      # NOT dropped
        cell = cells[(date(2026, 5, 2), "TR", None)]
        self.assertEqual(cell["impact"], 99)
        self.assertIsNone(cell["predicted_attendance"])          # holidays have no attendance

    def test_bridge_curve_merged_by_per_day_max(self):
        # Statutory single day (99); bridge widens to 3 days at 70/80/70.
        hol = _rec(
            event="Bayram", category="religious_holiday", source="diyanet",
            nearest_airport=None,
            start_date=date(2026, 5, 2), end_date=date(2026, 5, 2),
            impact_score=99,
            impact_by_day=(("2026-05-02", 99),),
            impact_by_day_bridge=(("2026-05-01", 70), ("2026-05-02", 80), ("2026-05-03", 70)),
        )
        cells = _features_by_cell(lakehouse.explode_features([hol], "run", TS))
        self.assertEqual(set(c[0] for c in cells), {date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3)})
        self.assertEqual(cells[(date(2026, 5, 1), "TR", None)]["impact"], 70)   # bridge-only day
        self.assertEqual(cells[(date(2026, 5, 2), "TR", None)]["impact"], 99)   # max(99, 80)
        self.assertEqual(cells[(date(2026, 5, 3), "TR", None)]["impact"], 70)

    def test_same_cell_aggregates_across_events(self):
        day = date(2026, 5, 2)
        a = _rec(
            event="Concert A", category="concert", source="ticketmaster",
            lat=41.0, lon=29.0, nearest_airport="IST",
            start_date=day, end_date=day, impact_score=40, predicted_attendance=1000,
            impact_by_day=(("2026-05-02", 40),), impact_by_day_bridge=(("2026-05-02", 40),),
        )
        b = _rec(
            event="Match B", category="sports", source="football",
            lat=41.0, lon=29.1, nearest_airport="IST",
            start_date=day, end_date=day, impact_score=55, predicted_attendance=500,
            impact_by_day=(("2026-05-02", 55),), impact_by_day_bridge=(("2026-05-02", 55),),
        )
        cells = _features_by_cell(lakehouse.explode_features([a, b], "run", TS))
        cell = cells[(day, "TR", "IST")]
        self.assertEqual(cell["impact"], 55)                       # max
        self.assertEqual(cell["predicted_attendance"], 1500)       # sum
        self.assertEqual(cell["n_events"], 2)
        self.assertEqual(cell["sources"], "football,ticketmaster")  # sorted, distinct

    def test_attendance_none_when_no_contributor_has_one(self):
        a = _rec(
            event="Concert", category="concert", source="ticketmaster",
            nearest_airport="IST", start_date=date(2026, 5, 2), end_date=date(2026, 5, 2),
            impact_score=40, predicted_attendance=None,
            impact_by_day=(("2026-05-02", 40),), impact_by_day_bridge=(("2026-05-02", 40),),
        )
        cell = _features_by_cell(lakehouse.explode_features([a], "run", TS))[(date(2026, 5, 2), "TR", "IST")]
        self.assertIsNone(cell["predicted_attendance"])

    def test_fallback_curve_when_unenriched(self):
        # No curves at all -> flat impact_score over [start, end].
        rec = _rec(
            start_date=date(2026, 5, 1), end_date=date(2026, 5, 2),
            impact_score=33, nearest_airport=None,
            impact_by_day=None, impact_by_day_bridge=None,
        )
        cells = _features_by_cell(lakehouse.explode_features([rec], "run", TS))
        self.assertEqual(len(cells), 2)
        self.assertEqual(cells[(date(2026, 5, 1), "TR", None)]["impact"], 33)
        self.assertEqual(cells[(date(2026, 5, 2), "TR", None)]["impact"], 33)


class SchemaAlignmentTest(unittest.TestCase):
    def test_column_counts(self):
        self.assertEqual(len(lakehouse.RAW_COLUMNS), 20)
        self.assertEqual(len(lakehouse.FEATURE_COLUMNS), 9)


if __name__ == "__main__":
    unittest.main()

"""Integration test for the lakehouse Spark write — skipped when pyspark (or a
working local Spark/Java) is unavailable, so the offline suite still passes.

On the THY cluster (or any box with pyspark + Java) this writes both tables to a
temp warehouse and reads them back, exercising the real schemas and saveAsTable.
"""

import shutil
import tempfile
import unittest
from datetime import date, datetime, timezone

from special_days.models import SpecialDate
from special_days.sinks import lakehouse

try:
    from pyspark.sql import SparkSession
    _HAS_PYSPARK = True
except Exception:  # pragma: no cover - import guard
    _HAS_PYSPARK = False

TS = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)


def _records():
    hol = SpecialDate(
        event="Bayram", start_date=date(2026, 5, 2), end_date=date(2026, 5, 2),
        city="Nationwide (TR)", category="religious_holiday", country="TR", source="diyanet",
        impact_score=99, nearest_airport=None,
        impact_by_day=(("2026-05-02", 99),),
        impact_by_day_bridge=(("2026-05-01", 70), ("2026-05-02", 99), ("2026-05-03", 70)),
    )
    ev = SpecialDate(
        event="Concert", start_date=date(2026, 5, 2), end_date=date(2026, 5, 3),
        city="Istanbul", category="concert", country="TR", source="ticketmaster",
        lat=41.0, lon=29.0, nearest_airport="IST", impact_score=40, predicted_attendance=1000,
        impact_by_day=(("2026-05-02", 40), ("2026-05-03", 40)),
        impact_by_day_bridge=(("2026-05-02", 40), ("2026-05-03", 40)),
    )
    return [hol, ev]


@unittest.skipUnless(_HAS_PYSPARK, "pyspark not installed")
class LakehouseSparkRoundtripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="special_days_lh_")
        try:
            cls.spark = (
                SparkSession.builder
                .master("local[1]")
                .appName("special-days-lakehouse-test")
                .config("spark.sql.warehouse.dir", cls.tmp)
                .config("spark.ui.enabled", "false")
                .getOrCreate()
            )
        except Exception as exc:  # Java missing etc. -> skip rather than error
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise unittest.SkipTest(f"cannot start local Spark: {exc}")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "spark", None) is not None:
            cls.spark.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_write_creates_both_tables(self):
        run_id = lakehouse.write(
            _records(),
            spark=self.spark,
            database="special_events_test",
            location=self.tmp + "/lake",
        )
        self.assertTrue(run_id)

        raw = self.spark.table("special_events_test.special_days_raw")
        self.assertEqual(raw.count(), 2)
        self.assertEqual(list(raw.columns), list(lakehouse.RAW_COLUMNS))

        feat = self.spark.table("special_events_test.special_days_features")
        self.assertEqual(list(feat.columns), list(lakehouse.FEATURE_COLUMNS))
        # 3 national-holiday days (None airport) + 2 event days (IST) = 5 cells.
        self.assertEqual(feat.count(), 5)

        # National holiday rows are preserved with a NULL airport (not dropped).
        national = feat.where("airport IS NULL").count()
        self.assertEqual(national, 3)

    def test_overwrite_is_idempotent(self):
        for _ in range(2):
            lakehouse.write(
                _records(),
                spark=self.spark,
                database="special_events_test",
                location=self.tmp + "/lake",
            )
        feat = self.spark.table("special_events_test.special_days_features")
        self.assertEqual(feat.count(), 5)  # overwrite, not append


if __name__ == "__main__":
    unittest.main()

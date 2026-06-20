import threading
import unittest
from datetime import date

from special_days import enrich
from special_days.models import SpecialDate
from special_days.scoring import ScoreResult


def event(city, lat, lon, start="2026-07-01", end=None, category="concert"):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else s
    return SpecialDate("Show", s, e, city, category, "TR", "ticketmaster", lat=lat, lon=lon)


def holiday(name, start, end, category="religious_holiday"):
    return SpecialDate(name, date.fromisoformat(start), date.fromisoformat(end),
                       "Nationwide (TR)", category, "TR", "diyanet")


class HaversineTest(unittest.TestCase):
    def test_known_distance(self):
        # Istanbul city center to IST airport is roughly 35 km.
        d = enrich.haversine_km(41.0082, 28.9784, 41.275, 28.752)
        self.assertTrue(25 < d < 45, d)

    def test_zero_distance(self):
        self.assertAlmostEqual(enrich.haversine_km(41.0, 29.0, 41.0, 29.0), 0.0)


class NearestAirportTest(unittest.TestCase):
    def test_finds_istanbul_airport(self):
        match = enrich.nearest_airport(41.0082, 28.9784, catchment_km=150)
        self.assertIsNotNone(match)
        self.assertIn(match[0], {"IST", "SAW"})  # both are Istanbul airports
        self.assertLess(match[1], 60)

    def test_none_outside_catchment(self):
        # Mid-Atlantic: nothing within 150 km.
        self.assertIsNone(enrich.nearest_airport(30.0, -40.0, catchment_km=150))


class ImpactTest(unittest.TestCase):
    def test_longer_holiday_scores_higher(self):
        short = holiday("Short", "2026-05-27", "2026-05-27")
        long = holiday("Long", "2026-05-26", "2026-06-03")  # 9-day bayram
        self.assertGreater(
            enrich.impact_score(long, None), enrich.impact_score(short, None)
        )

    def test_score_is_clamped_0_100(self):
        s = enrich.impact_score(holiday("X", "2026-01-01", "2027-01-01"), 10.0)
        self.assertTrue(0 <= s <= 100)

    def test_incomplete_coordinates_not_penalized(self):
        # lat present but lon missing must score the same as no coordinates,
        # not be penalised as "located but no airport in range".
        both_none = event("X", None, None)
        lat_only = event("X", 41.0, None)
        self.assertEqual(
            enrich.impact_score(lat_only, None), enrich.impact_score(both_none, None)
        )


class DropLongEventsTest(unittest.TestCase):
    def test_drops_long_event_keeps_holiday(self):
        long_event = event("İzmir", 38.4, 27.1, "2026-05-01", "2026-09-01")  # 4-month "season ticket"
        short_event = event("İzmir", 38.4, 27.1, "2026-07-01", "2026-07-02")
        summer_break = SpecialDate(
            "Yaz tatili", date(2026, 6, 27), date(2026, 9, 13), "Nationwide (TR)",
            "school_holiday", "TR", "meb",
        )
        kept = enrich.drop_long_events([long_event, short_event, summer_break], max_event_span_days=30)
        names_sources = {(r.event, r.source) for r in kept}
        self.assertIn(("Show", "ticketmaster"), names_sources)  # short event kept
        self.assertIn(("Yaz tatili", "meb"), names_sources)  # long holiday kept
        self.assertEqual(sum(1 for r in kept if r.source == "ticketmaster"), 1)  # long event dropped

    def test_zero_disables_filter(self):
        long_event = event("İzmir", 38.4, 27.1, "2026-05-01", "2026-09-01")
        self.assertEqual(len(enrich.drop_long_events([long_event], max_event_span_days=0)), 1)


class EnrichTest(unittest.TestCase):
    def test_event_gets_airport_and_impact(self):
        [out] = enrich.enrich([event("İstanbul", 41.0082, 28.9784)])
        self.assertIn(out.nearest_airport, {"IST", "SAW"})
        self.assertIsNotNone(out.airport_distance_km)
        self.assertIsInstance(out.impact_score, int)

    def test_national_holiday_has_no_airport_but_has_impact(self):
        [out] = enrich.enrich([holiday("Ramazan Bayramı", "2026-03-19", "2026-03-22")])
        self.assertIsNone(out.nearest_airport)
        self.assertIsInstance(out.impact_score, int)

    def test_attendance_flows_from_scorer(self):
        class AttendanceScorer:
            def score(self, record):
                return ScoreResult(70, 12345)

        [out] = enrich.enrich([event("İstanbul", 41.0, 29.0)], scorer=AttendanceScorer())
        self.assertEqual(out.impact_score, 70)
        self.assertEqual(out.predicted_attendance, 12345)

    def test_heuristic_leaves_attendance_blank(self):
        [out] = enrich.enrich([event("İstanbul", 41.0, 29.0)])
        self.assertIsNone(out.predicted_attendance)


class _DayScorer:
    """Returns the start day, so results depend on (and reveal) record order."""

    def score(self, record):
        return ScoreResult(record.start_date.day, None)


class ConcurrencyTest(unittest.TestCase):
    def _records(self, n):
        return [event("İstanbul", 41.0, 29.0, start=f"2026-07-0{i}") for i in range(1, n + 1)]

    def test_concurrency_preserves_order_and_results(self):
        recs = self._records(5)
        seq = [r.impact_score for r in enrich.enrich(recs, scorer=_DayScorer(), concurrency=1)]
        par = [r.impact_score for r in enrich.enrich(recs, scorer=_DayScorer(), concurrency=4)]
        self.assertEqual(seq, [1, 2, 3, 4, 5])
        self.assertEqual(par, seq)

    def test_calls_actually_run_in_parallel(self):
        n = 4
        barrier = threading.Barrier(n, timeout=5)  # each call blocks until all n arrive

        class BarrierScorer:
            def score(self, record):
                barrier.wait()  # times out (BrokenBarrierError) if scoring were sequential
                return ScoreResult(50, None)

        out = enrich.enrich(self._records(n), scorer=BarrierScorer(), concurrency=n)
        self.assertEqual([r.impact_score for r in out], [50] * n)

    def test_first_error_propagates(self):
        class Boom:
            def score(self, record):
                raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            enrich.enrich(self._records(3), scorer=Boom(), concurrency=2)


if __name__ == "__main__":
    unittest.main()

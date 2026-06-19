import unittest
from datetime import date

from special_days import curve


class WeightsTest(unittest.TestCase):
    def test_single_day(self):
        self.assertEqual(curve.weights(date(2026, 7, 1), date(2026, 7, 1), 88), (("2026-07-01", 88),))

    def test_pure_v_over_weekday_range(self):
        # Mon 2026-03-09 .. Fri 2026-03-13 — no weekends, so a clean V.
        w = curve.weights(date(2026, 3, 9), date(2026, 3, 13), 100)
        self.assertEqual(
            w,
            (
                ("2026-03-09", 100), ("2026-03-10", 75), ("2026-03-11", 50),
                ("2026-03-12", 75), ("2026-03-13", 100),
            ),
        )

    def test_endpoints_equal_peak(self):
        w = curve.weights(date(2026, 3, 9), date(2026, 3, 13), 90)
        self.assertEqual(w[0][1], 90)
        self.assertEqual(w[-1][1], 90)

    def test_monotone_down_then_up_for_weekday_range(self):
        vals = [v for _, v in curve.weights(date(2026, 3, 9), date(2026, 3, 13), 100)]
        mid = len(vals) // 2
        self.assertEqual(vals[:mid + 1], sorted(vals[:mid + 1], reverse=True))  # down to middle
        self.assertEqual(vals[mid:], sorted(vals[mid:]))  # up from middle

    def test_weekend_forced_to_peak(self):
        # Mon 03-09 .. Sun 03-15: the interior Saturday (03-14) is a weekend -> peak.
        d = dict(curve.weights(date(2026, 3, 9), date(2026, 3, 15), 100))
        self.assertEqual(d["2026-03-14"], 100)  # Saturday forced to peak
        self.assertEqual(d["2026-03-15"], 100)  # Sunday (also endpoint)
        self.assertLess(d["2026-03-12"], 100)  # an interior weekday dips below peak

    def test_trough_near_fifty_percent(self):
        d = dict(curve.weights(date(2026, 3, 9), date(2026, 3, 13), 100))
        self.assertEqual(d["2026-03-11"], 50)  # exact middle ~ 50% of peak


if __name__ == "__main__":
    unittest.main()

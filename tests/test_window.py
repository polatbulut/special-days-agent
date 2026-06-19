import unittest
from datetime import date

from special_days.window import add_months, overlaps, resolve_window


class WindowTest(unittest.TestCase):
    def test_add_months_basic(self):
        self.assertEqual(add_months(date(2026, 6, 19), 12), date(2027, 6, 19))

    def test_add_months_crosses_year(self):
        self.assertEqual(add_months(date(2026, 9, 1), 6), date(2027, 3, 1))

    def test_add_months_clamps_day(self):
        # Jan 31 + 1 month -> Feb 28 (2026 not a leap year)
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_resolve_window_uses_given_start(self):
        start, end = resolve_window(date(2026, 6, 19), 12)
        self.assertEqual(start, date(2026, 6, 19))
        self.assertEqual(end, date(2027, 6, 19))

    def test_resolve_window_defaults_to_today(self):
        start, end = resolve_window(None, 3)
        self.assertEqual(add_months(start, 3), end)

    def test_overlaps(self):
        w0, w1 = date(2026, 6, 1), date(2027, 6, 1)
        self.assertTrue(overlaps(date(2026, 5, 25), date(2026, 6, 5), w0, w1))  # straddles start
        self.assertTrue(overlaps(date(2026, 8, 1), date(2026, 8, 2), w0, w1))  # inside
        self.assertFalse(overlaps(date(2027, 7, 1), date(2027, 7, 2), w0, w1))  # after


if __name__ == "__main__":
    unittest.main()

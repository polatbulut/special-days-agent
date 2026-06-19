import unittest
from datetime import date

from special_days.bridge import compute_bridge
from special_days.models import SpecialDate


def holiday(start, end, source="diyanet", country="TR"):
    return SpecialDate(
        "H", date.fromisoformat(start), date.fromisoformat(end),
        "Nationwide (TR)", "religious_holiday", country, source,
    )


def event(start, end):
    return SpecialDate(
        "E", date.fromisoformat(start), date.fromisoformat(end),
        "İstanbul", "concert", "TR", "ticketmaster",
    )


class ComputeBridgeTest(unittest.TestCase):
    # 2026-03-09 is a Monday; build examples around it.
    def test_mon_to_fri_grabs_both_weekends(self):
        # Mon 2026-03-09 .. Fri 2026-03-13 -> Sat 03-07 .. Sun 03-15
        bs, be = compute_bridge(holiday("2026-03-09", "2026-03-13"))
        self.assertEqual((bs, be), (date(2026, 3, 7), date(2026, 3, 15)))

    def test_mon_to_thu_bridges_friday(self):
        # Mon .. Thu (multi-day, G=2) -> Sat before .. Sun after the bridged Fri
        bs, be = compute_bridge(holiday("2026-03-09", "2026-03-12"))
        self.assertEqual((bs, be), (date(2026, 3, 7), date(2026, 3, 15)))

    def test_single_midweek_day_not_bridged(self):
        # Wed 2026-03-11, single-day (G=1): 2 working days to either weekend -> none
        bs, be = compute_bridge(holiday("2026-03-11", "2026-03-11"))
        self.assertEqual((bs, be), (date(2026, 3, 11), date(2026, 3, 11)))

    def test_single_thursday_bridges_one_day(self):
        # Thu 2026-03-12 single-day (G=1): Fri is 1 working day -> Thu..Sun
        bs, be = compute_bridge(holiday("2026-03-12", "2026-03-12"))
        self.assertEqual((bs, be), (date(2026, 3, 12), date(2026, 3, 15)))

    def test_real_ramazan_2027(self):
        # Ramazan Bayramı 2027: Mon 03-08 .. Thu 03-11 (arife Mon) -> Sat 03-06..Sun 03-14
        bs, be = compute_bridge(holiday("2027-03-08", "2027-03-11"))
        self.assertEqual(bs, date(2027, 3, 6))
        self.assertEqual(be, date(2027, 3, 14))
        self.assertLess(bs, date(2027, 3, 8))
        self.assertGreater(be, date(2027, 3, 11))

    def test_events_are_not_bridged(self):
        bs, be = compute_bridge(event("2026-03-09", "2026-03-13"))
        self.assertEqual((bs, be), (date(2026, 3, 9), date(2026, 3, 13)))

    def test_international_holiday_not_bridged(self):
        bs, be = compute_bridge(holiday("2026-03-09", "2026-03-13", source="nager", country="DE"))
        self.assertEqual((bs, be), (date(2026, 3, 9), date(2026, 3, 13)))


if __name__ == "__main__":
    unittest.main()

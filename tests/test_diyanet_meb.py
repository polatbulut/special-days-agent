import unittest
from datetime import date
from unittest import mock

from special_days.sources import diyanet, meb

DIYANET_SAMPLE = [
    {"name": "Ramazan Bayramı", "start": "2026-03-19", "end": "2026-03-22"},
    {"name": "Kurban Bayramı", "start": "2026-05-26", "end": "2026-05-30"},
    {"name": "Kurban Bayramı", "start": "2027-05-15", "end": "2027-05-19"},
]
MEB_SAMPLE = [
    {"name": "Yarıyıl tatili", "start": "2026-01-19", "end": "2026-01-30"},
    {"name": "Yaz tatili", "start": "2026-06-27", "end": "2026-09-13"},
]


class DiyanetTest(unittest.TestCase):
    def test_filters_to_window_with_overlap(self):
        with mock.patch("special_days.sources.diyanet.load_diyanet", return_value=DIYANET_SAMPLE):
            rows = diyanet.fetch_in_window(date(2026, 5, 1), date(2026, 12, 31))
        # Kurban 2026 (May) is in window; Ramazan 2026 (March) and Kurban 2027 are not.
        self.assertEqual([(r.event, r.start_date.isoformat()) for r in rows],
                         [("Kurban Bayramı", "2026-05-26")])
        self.assertEqual(rows[0].category, "religious_holiday")
        self.assertEqual(rows[0].source, "diyanet")
        self.assertEqual(rows[0].city, "Nationwide (TR)")

    def test_skips_malformed_records(self):
        bad = [{"name": "Broken", "start": "nope", "end": "2026-01-02"}, DIYANET_SAMPLE[0]]
        with mock.patch("special_days.sources.diyanet.load_diyanet", return_value=bad):
            rows = diyanet.fetch_in_window(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual([r.event for r in rows], ["Ramazan Bayramı"])


class MebTest(unittest.TestCase):
    def test_overlapping_break_included(self):
        with mock.patch("special_days.sources.meb.load_meb", return_value=MEB_SAMPLE):
            rows = meb.fetch_in_window(date(2026, 7, 1), date(2026, 7, 31))
        # Summer break spans July; semester break (Jan) does not.
        self.assertEqual([r.event for r in rows], ["Yaz tatili"])
        self.assertEqual(rows[0].category, "school_holiday")
        self.assertEqual(rows[0].source, "meb")


if __name__ == "__main__":
    unittest.main()

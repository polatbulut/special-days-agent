import unittest
from datetime import date
from unittest import mock

from special_days.sources import nager

SAMPLE = [
    {
        "date": "2026-01-01",
        "localName": "Yılbaşı",
        "name": "New Year's Day",
        "countryCode": "TR",
        "types": ["Public"],
    },
    {
        "date": "2026-10-29",
        "localName": "Cumhuriyet Bayramı",
        "name": "Republic Day",
        "countryCode": "TR",
        "types": ["Public"],
    },
]


class NagerTest(unittest.TestCase):
    @mock.patch("special_days.sources.nager.get_json", return_value=SAMPLE)
    def test_maps_holidays_to_special_dates(self, _get):
        rows = nager.fetch_holidays("tr", 2026)
        self.assertEqual(len(rows), 2)

        first = rows[0]
        self.assertEqual(first.event, "Yılbaşı")  # local name preferred
        self.assertEqual(first.start_date, date(2026, 1, 1))
        self.assertEqual(first.end_date, first.start_date)  # single-day
        self.assertEqual(first.city, "Nationwide (TR)")
        self.assertEqual(first.category, "public_holiday")
        self.assertEqual(first.source, "nager")

    @mock.patch("special_days.sources.nager.get_json", return_value=SAMPLE)
    def test_can_prefer_english_name(self, _get):
        rows = nager.fetch_holidays("TR", 2026, prefer_local_name=False)
        self.assertEqual(rows[0].event, "New Year's Day")

    @mock.patch("special_days.sources.nager.get_json", return_value=SAMPLE)
    def test_builds_expected_url(self, get_json):
        nager.fetch_holidays("tr", 2026)
        get_json.assert_called_once_with(
            "https://date.nager.at/api/v3/PublicHolidays/2026/TR"
        )

    def test_one_bad_record_does_not_discard_the_rest(self):
        mixed = [
            {"date": "2026-01-01", "localName": "Yılbaşı", "name": "New Year's Day"},
            {"localName": "Missing date"},  # no "date" key
            {"date": None, "localName": "Null date"},  # null date
            {"date": "not-a-date", "localName": "Bad date"},  # unparseable
            {"date": "2026-10-29", "localName": "Cumhuriyet Bayramı"},
        ]
        with mock.patch("special_days.sources.nager.get_json", return_value=mixed):
            rows = nager.fetch_holidays("TR", 2026)
        self.assertEqual([r.event for r in rows], ["Yılbaşı", "Cumhuriyet Bayramı"])

    def test_window_spans_years_and_filters(self):
        per_year = {
            2026: [{"date": "2026-12-31", "localName": "A"}],
            2027: [{"date": "2027-01-01", "localName": "B"}, {"date": "2027-12-31", "localName": "C"}],
        }
        with mock.patch(
            "special_days.sources.nager.get_json", side_effect=lambda url: per_year[int(url.split("/")[-2])]
        ):
            rows = nager.fetch_holidays_in_window("TR", date(2026, 12, 1), date(2027, 6, 1))
        # A (Dec 2026) and B (Jan 2027) are in window; C (Dec 2027) is not.
        self.assertEqual([r.event for r in rows], ["A", "B"])


if __name__ == "__main__":
    unittest.main()

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
        self.assertEqual(first.category, "holiday")
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


if __name__ == "__main__":
    unittest.main()

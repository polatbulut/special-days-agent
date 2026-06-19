import unittest
from datetime import date
from unittest import mock

from special_days.sources import ticketmaster

EVENT_FULL = {
    "name": "Tarkan Live",
    "dates": {"start": {"localDate": "2026-07-15"}, "end": {"localDate": "2026-07-16"}},
    "classifications": [{"segment": {"name": "Music"}}],
    "_embedded": {
        "venues": [
            {
                "name": "Arena",
                "city": {"name": "Istanbul"},
                "location": {"latitude": "41.0082", "longitude": "28.9784"},
            }
        ]
    },
}
EVENT_NO_END = {
    "name": "Jazz Night",
    "dates": {"start": {"localDate": "2026-08-01"}},
    "_embedded": {"venues": [{"city": {"name": "İzmir"}}]},
}
EVENT_NO_DATE = {"name": "TBA", "dates": {}}
EVENT_NO_VENUE = {"name": "Open Air", "dates": {"start": {"localDate": "2026-09-09"}}}


class ParseEventTest(unittest.TestCase):
    def test_full_event(self):
        sd = ticketmaster._parse_event(EVENT_FULL, "TR")
        self.assertEqual(sd.event, "Tarkan Live")
        self.assertEqual(sd.start_date, date(2026, 7, 15))
        self.assertEqual(sd.end_date, date(2026, 7, 16))
        self.assertEqual(sd.city, "Istanbul")
        self.assertEqual(sd.category, "concert")  # Music segment -> concert
        self.assertAlmostEqual(sd.lat, 41.0082)
        self.assertAlmostEqual(sd.lon, 28.9784)

    def test_missing_end_falls_back_to_start(self):
        sd = ticketmaster._parse_event(EVENT_NO_END, "TR")
        self.assertEqual(sd.end_date, sd.start_date)
        self.assertEqual(sd.city, "İzmir")

    def test_category_defaults_to_event_without_classification(self):
        self.assertEqual(ticketmaster._parse_event(EVENT_NO_VENUE, "TR").category, "event")

    def test_sports_segment_maps_to_sports(self):
        raw = {
            "name": "Derby",
            "dates": {"start": {"localDate": "2026-10-01"}},
            "classifications": [{"segment": {"name": "Sports"}}],
        }
        self.assertEqual(ticketmaster._parse_event(raw, "TR").category, "sports")

    def test_missing_start_date_is_skipped(self):
        self.assertIsNone(ticketmaster._parse_event(EVENT_NO_DATE, "TR"))

    def test_missing_venue_is_unknown_city(self):
        sd = ticketmaster._parse_event(EVENT_NO_VENUE, "TR")
        self.assertEqual(sd.city, "Unknown")

    def test_end_before_start_is_clamped(self):
        backwards = {
            "name": "Bad Range",
            "dates": {"start": {"localDate": "2026-07-15"}, "end": {"localDate": "2026-07-10"}},
        }
        sd = ticketmaster._parse_event(backwards, "TR")
        self.assertEqual(sd.end_date, sd.start_date)
        self.assertGreaterEqual(sd.end_date, sd.start_date)


class FetchEventsTest(unittest.TestCase):
    def test_paginates_and_stops_on_last_page(self):
        page0 = {"_embedded": {"events": [EVENT_FULL, EVENT_NO_END]}, "page": {"totalPages": 1}}
        with mock.patch(
            "special_days.sources.ticketmaster.get_json", return_value=page0
        ) as get_json:
            rows = ticketmaster.fetch_events("TR", "KEY", date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(rows), 2)
        self.assertEqual(get_json.call_count, 1)  # stopped after the only page

    def test_stops_on_empty_page(self):
        empty = {"_embedded": {"events": []}, "page": {"totalPages": 5}}
        with mock.patch(
            "special_days.sources.ticketmaster.get_json", return_value=empty
        ) as get_json:
            rows = ticketmaster.fetch_events("TR", "KEY")
        self.assertEqual(rows, [])
        self.assertEqual(get_json.call_count, 1)


if __name__ == "__main__":
    unittest.main()

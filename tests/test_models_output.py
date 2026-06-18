import json
import unittest
from datetime import date

from special_days.models import SpecialDate
from special_days.output import render_csv, render_json, render_table


def make(event="Concert", start="2026-07-01", end=None, city="Istanbul"):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else s
    return SpecialDate(event, s, e, city, "event", "TR", "ticketmaster")


class SpecialDateTest(unittest.TestCase):
    def test_core_row_is_the_four_headline_fields(self):
        row = make(event="Bayram", start="2026-03-20", end="2026-03-22", city="Nationwide (TR)")
        self.assertEqual(
            row.core_row(),
            ("Bayram", "2026-03-20", "2026-03-22", "Nationwide (TR)"),
        )

    def test_to_dict_serialises_dates_as_iso_strings(self):
        d = make().to_dict()
        self.assertEqual(d["start_date"], "2026-07-01")
        self.assertEqual(d["end_date"], "2026-07-01")
        self.assertEqual(d["category"], "event")

    def test_sort_key_orders_by_date_then_name(self):
        rows = [make(event="B", start="2026-07-02"), make(event="A", start="2026-07-01")]
        rows.sort(key=SpecialDate.sort_key)
        self.assertEqual([r.event for r in rows], ["A", "B"])


class OutputTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            make(event="New Year", start="2026-01-01", city="Nationwide (TR)"),
            make(event="Festival", start="2026-07-01", end="2026-07-03", city="İzmir"),
        ]

    def test_csv_has_header_and_four_columns(self):
        out = render_csv(self.rows)
        lines = out.splitlines()
        self.assertEqual(lines[0], "event,start_date,end_date,city")
        self.assertIn("Festival,2026-07-01,2026-07-03,İzmir", out)

    def test_table_includes_event_and_city(self):
        out = render_table(self.rows)
        self.assertIn("Event", out)
        self.assertIn("Festival", out)
        self.assertIn("2 special date(s).", out)

    def test_table_empty(self):
        self.assertEqual(render_table([]), "No special dates found.")

    def test_json_round_trips(self):
        parsed = json.loads(render_json(self.rows))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["event"], "New Year")


if __name__ == "__main__":
    unittest.main()

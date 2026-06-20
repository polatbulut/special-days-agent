import json
import unittest
from datetime import date

from special_days.models import SpecialDate
from special_days.output import render_csv, render_json, render_table


def make(event="Concert", start="2026-07-01", end=None, city="Istanbul", airport=None, impact=None, bstart=None, bend=None):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else s
    return SpecialDate(
        event, s, e, city, "event", "TR", "ticketmaster",
        nearest_airport=airport, impact_score=impact,
        bridge_start=date.fromisoformat(bstart) if bstart else None,
        bridge_end=date.fromisoformat(bend) if bend else None,
    )


class SpecialDateTest(unittest.TestCase):
    def test_core_row_is_the_ten_headline_fields(self):
        row = make(
            event="Bayram", start="2026-03-20", end="2026-03-22",
            city="Nationwide (TR)", airport="IST", impact=88,
            bstart="2026-03-19", bend="2026-03-23",
        )
        self.assertEqual(
            row.core_row(),
            ("Bayram", "2026-03-20", "2026-03-22", "Nationwide (TR)", "ticketmaster",
             "IST", "88", "", "2026-03-19", "2026-03-23"),  # attendance blank (index 7)
        )

    def test_core_row_has_source_and_blanks_for_missing_enrichment(self):
        row = make(event="X").core_row()
        self.assertEqual(row[4], "ticketmaster")  # source
        # airport, impact, attendance, bridge_start, bridge_end all blank
        self.assertEqual(row[5:], ("", "", "", "", ""))

    def test_to_dict_serialises_dates_as_iso_strings(self):
        d = make(airport="IST", impact=50).to_dict()
        self.assertEqual(d["start_date"], "2026-07-01")
        self.assertEqual(d["nearest_airport"], "IST")
        self.assertEqual(d["impact_score"], 50)

    def test_sort_key_orders_by_date_then_name(self):
        rows = [make(event="B", start="2026-07-02"), make(event="A", start="2026-07-01")]
        rows.sort(key=SpecialDate.sort_key)
        self.assertEqual([r.event for r in rows], ["A", "B"])


class OutputTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            make(event="New Year", start="2026-01-01", city="Nationwide (TR)", impact=70),
            make(event="Festival", start="2026-07-01", end="2026-07-03", city="İzmir", airport="ADB", impact=63),
        ]

    def test_csv_header_and_rows(self):
        out = render_csv(self.rows)
        lines = out.splitlines()
        self.assertEqual(
            lines[0],
            "event,start_date,end_date,city,source,nearest_airport,impact,"
            "predicted_attendance,bridge_start,bridge_end,impact_by_day,impact_by_day_bridge",
        )
        self.assertIn("Festival,2026-07-01,2026-07-03,İzmir,ticketmaster,ADB,63", out)

    def test_table_includes_event_and_new_columns(self):
        out = render_table(self.rows)
        self.assertIn("Nearest airport", out)
        self.assertIn("Impact", out)
        self.assertIn("Festival", out)
        self.assertIn("2 special date(s).", out)

    def test_table_empty(self):
        self.assertEqual(render_table([]), "No special dates found.")

    def test_json_round_trips(self):
        parsed = json.loads(render_json(self.rows))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["event"], "New Year")
        self.assertEqual(parsed[1]["nearest_airport"], "ADB")


if __name__ == "__main__":
    unittest.main()

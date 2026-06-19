import os
import tempfile
import unittest
from datetime import date

from openpyxl import load_workbook

from special_days.models import SpecialDate
from special_days.xlsx_writer import write_xlsx

HEADER = ["Event", "Start date", "End date", "City", "Nearest airport", "Impact"]


def make(event, city, start="2026-07-01", end=None, airport=None, impact=None):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else s
    return SpecialDate(
        event, s, e, city, "event", "TR", "ticketmaster",
        nearest_airport=airport, impact_score=impact,
    )


class XlsxWriterTest(unittest.TestCase):
    def _write_and_load(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.xlsx")
            write_xlsx(rows, path)
            workbook = load_workbook(path)
        return workbook.active

    def test_sheet_name_and_bold_header(self):
        sheet = self._write_and_load([make("Tarkan Live", "İstanbul")])
        self.assertEqual(sheet.title, "Special Dates")
        self.assertEqual([c.value for c in sheet[1]], HEADER)
        self.assertTrue(all(c.font.bold for c in sheet[1]))

    def test_rows_have_real_dates_airport_impact_and_unicode(self):
        sheet = self._write_and_load(
            [make("Tarkan Live", "İstanbul", "2026-07-15", "2026-07-16", airport="IST", impact=72)]
        )
        self.assertEqual(sheet["A2"].value, "Tarkan Live")
        self.assertEqual(sheet["D2"].value, "İstanbul")  # unicode preserved
        self.assertEqual(sheet["E2"].value, "IST")
        self.assertEqual(sheet["F2"].value, 72)  # numeric impact cell
        start = sheet["B2"].value  # real date cell, not text
        self.assertEqual((start.year, start.month, start.day), (2026, 7, 15))
        self.assertEqual(sheet["B2"].number_format, "yyyy-mm-dd")

    def test_freeze_panes_and_autofilter(self):
        sheet = self._write_and_load([make("A", "X"), make("B", "Y")])
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet.auto_filter.ref, "A1:F3")  # header + 2 rows, 6 cols

    def test_empty_rows_still_valid(self):
        sheet = self._write_and_load([])
        self.assertEqual([c.value for c in sheet[1]], HEADER)
        self.assertEqual(sheet.max_row, 1)  # header only


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
import zipfile
from datetime import date

from special_days.models import SpecialDate
from special_days.xlsx_writer import _col, write_xlsx

REQUIRED_PARTS = [
    "[Content_Types].xml",
    "_rels/.rels",
    "xl/workbook.xml",
    "xl/_rels/workbook.xml.rels",
    "xl/worksheets/sheet1.xml",
]


def make(event, city, start="2026-07-01", end=None):
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else s
    return SpecialDate(event, s, e, city, "event", "TR", "ticketmaster")


class XlsxWriterTest(unittest.TestCase):
    def _write_and_read(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.xlsx")
            write_xlsx(rows, path)
            self.assertTrue(zipfile.is_zipfile(path))
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        return names, sheet

    def test_valid_zip_with_required_parts(self):
        names, _ = self._write_and_read([make("Tarkan Live", "İstanbul")])
        for part in REQUIRED_PARTS:
            self.assertIn(part, names)

    def test_header_and_rows_present(self):
        _, sheet = self._write_and_read(
            [make("Tarkan Live", "İstanbul", "2026-07-15", "2026-07-16")]
        )
        self.assertIn("Event", sheet)  # header
        self.assertIn("Tarkan Live", sheet)
        self.assertIn("İstanbul", sheet)  # unicode preserved
        self.assertIn("2026-07-15", sheet)
        self.assertIn("2026-07-16", sheet)

    def test_escapes_xml_special_chars(self):
        _, sheet = self._write_and_read([make("Rock & Roll <Live>", "İzmir")])
        self.assertIn("Rock &amp; Roll &lt;Live&gt;", sheet)
        self.assertNotIn("<Live>", sheet)

    def test_empty_rows_still_valid(self):
        names, sheet = self._write_and_read([])
        self.assertIn("xl/worksheets/sheet1.xml", names)
        self.assertIn("Event", sheet)  # header still written

    def test_column_letters(self):
        self.assertEqual(_col(1), "A")
        self.assertEqual(_col(4), "D")
        self.assertEqual(_col(27), "AA")


if __name__ == "__main__":
    unittest.main()

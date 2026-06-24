import unittest
from datetime import date
from unittest import mock

from special_days.sources import eventseye

# Real EventsEye markup shape: one <table class="tradeshows"> with a <thead> row
# (<th> cells, must be ignored) and <tbody> rows; the date cell is
# "MM/DD/YYYY<br><i>N days</i>"; a pages-links block carries the "Next" link.
PAGE_1 = """
<html><body>
<table class="tradeshows">
  <caption>214 Trade Shows in Turkey</caption>
  <thead>
    <tr><th>Exhibition Name</th><th>Cycle</th><th>Venue</th><th>Date</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><a href="f-maden-turkey-18914-1.html"><b>MADEN TURKEY</b><i>Mining &amp; Machinery Fair</i></a></td>
      <td>every 2 years</td>
      <td>
        <a href="cy1_trade-shows-istanbul.html">Istanbul</a>
        <a href="pl1_trade-shows_istanbul_443.html">T&uuml;yap Fair Center</a>
      </td>
      <td>04/08/2026<br><i>4 days</i></td>
    </tr>
    <tr>
      <td><a href="f-rubber-istanbul-8203-1.html"><b>RUBBER ISTANBUL</b><i>Rubber Industry Fair</i></a></td>
      <td>once a year</td>
      <td>
        <a href="cy1_trade-shows-istanbul.html">Istanbul</a>
        <a href="pl1_trade-shows_istanbul_999.html">Istanbul Expo Center</a>
      </td>
      <td>11/05/2026<br><i>1 day</i></td>
    </tr>
    <tr>
      <td><a href="f-future-expo-9999-1.html"><b>FUTURE EXPO</b><i>Far-future fair</i></a></td>
      <td>once a year</td>
      <td><a href="cy1_trade-shows-izmir.html">Izmir</a></td>
      <td>03/15/2027<br><i>2 days</i></td>
    </tr>
  </tbody>
</table>
<div class="pages-links">
  <div><a href="" title="first page"><u>Trade Shows in Turkey (first page)</u></a></div>
  <div><a href="c1_trade-shows_turkey_1.html"><u>Next</u></a></div>
</div>
</body></html>
"""

# Second page: every fair starts past the window end -> paging stops early.
PAGE_2 = """
<table class="tradeshows">
  <tbody>
    <tr>
      <td><a href="f-late-a-1.html"><b>LATE FAIR A</b><i>x</i></a></td>
      <td>once a year</td>
      <td><a href="cy1.html">Ankara</a></td>
      <td>01/10/2027<br><i>2 days</i></td>
    </tr>
    <tr>
      <td><a href="f-late-b-1.html"><b>LATE FAIR B</b><i>y</i></a></td>
      <td>once a year</td>
      <td><a href="cy1.html">Bursa</a></td>
      <td>02/20/2027<br><i>3 days</i></td>
    </tr>
  </tbody>
</table>
<div class="pages-links"><div><a href="c1_trade-shows_turkey_2.html"><u>Next</u></a></div></div>
"""

WINDOW = (date(2026, 4, 1), date(2026, 12, 31))


class ParseDateTest(unittest.TestCase):
    def test_month_day_year(self):
        self.assertEqual(eventseye._parse_date("04/08/2026"), date(2026, 4, 8))

    def test_day_month_fallback_when_first_field_over_12(self):
        # 27 cannot be a month -> treated as DD/MM (27 March 2026)
        self.assertEqual(eventseye._parse_date("27/03/2026"), date(2026, 3, 27))

    def test_picks_leading_date_with_trailing_duration(self):
        self.assertEqual(eventseye._parse_date("11/05/2026<br><i>3 days</i>"), date(2026, 11, 5))

    def test_invalid_returns_none(self):
        self.assertIsNone(eventseye._parse_date("not a date"))
        self.assertIsNone(eventseye._parse_date("13/45/2026"))  # 45 invalid either way


class ParseRowTest(unittest.TestCase):
    def _first_row_cells(self, html):
        table = eventseye._TABLE_RE.search(html)
        row = eventseye._ROW_RE.findall(table.group(1))[1]  # [0] is the <thead> row
        return eventseye._CELL_RE.findall(row)

    def test_full_row(self):
        sd = eventseye._parse_row(self._first_row_cells(PAGE_1), "TR", eventseye.BASE_URL)
        self.assertEqual(sd.event, "MADEN TURKEY")
        self.assertEqual(sd.start_date, date(2026, 4, 8))
        self.assertEqual(sd.end_date, date(2026, 4, 11))  # start + (4 - 1) days
        self.assertEqual(sd.city, "Istanbul")
        self.assertEqual(sd.category, "expo")
        self.assertEqual(sd.country, "TR")
        self.assertEqual(sd.source, "eventseye")
        self.assertIsNone(sd.lat)  # EventsEye has no coordinates
        self.assertIsNone(sd.lon)

    def test_entities_decoded_and_detail_url_absolute(self):
        sd = eventseye._parse_row(self._first_row_cells(PAGE_1), "TR", eventseye.BASE_URL)
        self.assertEqual(sd.raw["venue"], "Tüyap Fair Center")  # &uuml; decoded
        self.assertEqual(sd.raw["description"], "Mining & Machinery Fair")  # &amp; decoded
        self.assertEqual(sd.raw["url"], "https://www.eventseye.com/fairs/f-maden-turkey-18914-1.html")

    def test_no_organizer_pii_collected(self):
        sd = eventseye._parse_row(self._first_row_cells(PAGE_1), "TR", eventseye.BASE_URL)
        keys = set(sd.raw)
        self.assertFalse(keys & {"organizer", "email", "phone", "contact"})

    def test_header_row_is_skipped(self):
        table = eventseye._TABLE_RE.search(PAGE_1)
        header_cells = eventseye._CELL_RE.findall(eventseye._ROW_RE.findall(table.group(1))[0])
        self.assertIsNone(eventseye._parse_row(header_cells, "TR", eventseye.BASE_URL))


class FetchEventsTest(unittest.TestCase):
    def test_unmapped_country_skipped_without_fetch(self):
        with mock.patch("special_days.sources.eventseye.get_text") as get_text:
            rows = eventseye.fetch_events_in_window("ZZ", *WINDOW)  # ZZ: not a real country, unmapped
        self.assertEqual(rows, [])
        get_text.assert_not_called()

    def test_filters_to_window_and_follows_next(self):
        with mock.patch(
            "special_days.sources.eventseye.get_text", side_effect=[PAGE_1, PAGE_2]
        ) as get_text:
            rows = eventseye.fetch_events_in_window("TR", *WINDOW, pause=0)
        # FUTURE EXPO (2027) and both page-2 fairs are past the window -> dropped.
        self.assertEqual([r.event for r in rows], ["MADEN TURKEY", "RUBBER ISTANBUL"])
        self.assertEqual(get_text.call_count, 2)  # page 1 + page 2, then early stop

    def test_builds_correct_first_url(self):
        with mock.patch(
            "special_days.sources.eventseye.get_text", return_value="<html></html>"
        ) as get_text:
            eventseye.fetch_events_in_window("TR", *WINDOW, pause=0)
        self.assertEqual(
            get_text.call_args.args[0],
            "https://www.eventseye.com/fairs/c1_trade-shows_turkey.html",
        )

    def test_dedupes_same_fair_across_pages(self):
        # Page 2 repeats MADEN TURKEY (same name+date) and has no "Next" -> the
        # repeat is de-duplicated and paging stops.
        dup_page = """
        <table class="tradeshows"><tbody>
          <tr><td><a href="f-maden-turkey-18914-1.html"><b>MADEN TURKEY</b><i>x</i></a></td>
          <td>every 2 years</td><td><a href="cy1.html">Istanbul</a></td>
          <td>04/08/2026<br><i>4 days</i></td></tr>
        </tbody></table>
        """
        with mock.patch(
            "special_days.sources.eventseye.get_text", side_effect=[PAGE_1, dup_page]
        ):
            rows = eventseye.fetch_events_in_window("TR", *WINDOW, pause=0)
        self.assertEqual(sum(1 for r in rows if r.event == "MADEN TURKEY"), 1)

    def test_no_table_stops_cleanly(self):
        with mock.patch("special_days.sources.eventseye.get_text", return_value="<html>none</html>"):
            self.assertEqual(eventseye.fetch_events_in_window("TR", *WINDOW, pause=0), [])

    def test_rows_with_attributes_are_parsed(self):
        # EventsEye could add zebra-stripe row classes; rows must still parse.
        zebra = """
        <table class="tradeshows"><tbody>
          <tr class="odd"><td><a href="f-z-1.html"><b>ZEBRA FAIR</b><i>x</i></a></td>
          <td>once a year</td><td><a href="cy1.html">Istanbul</a></td>
          <td>09/10/2026<br><i>2 days</i></td></tr>
        </tbody></table>
        """
        with mock.patch("special_days.sources.eventseye.get_text", return_value=zebra):
            rows = eventseye.fetch_events_in_window("TR", *WINDOW, pause=0)
        self.assertEqual([r.event for r in rows], ["ZEBRA FAIR"])


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date
from unittest import mock

from special_days.sources import seminars

# Real ConferenceIndex shape: month-cards, each a "<strong>Month, YYYY</strong>"
# header + a "<ul>" of "<li> Mon DD <a href=… title=…>Title</a> - City, Country".
PAGE_1 = """
<div id="eventList">
<div class="card card-year card-year-2026 mb-2">
  <div class="card-header"><i class="far fa-calendar-alt"></i> <strong>July, 2026</strong></div>
  <div class="card-body"><ul class="list-unstyled">
    <li>
        Jul 29
<a href="https://conferenceindex.org/event/icmams-2026-july-istanbul-tr" title="International Conference on Management and Marketing Sciences (ICMAMS)">International Conference on Management and Marketing Sciences (ICMAMS)</a> - Istanbul, Turkey      </li>
    <li>
        Jul 30
<a href="/event/iceb-2026-july-antalya-tr" title="International Conference on Economics and Business (ICEB)">International Conference on Economics and Business (ICEB)</a> - Antalya, Turkey      </li>
  </ul></div>
</div>
<div class="card card-year card-year-2027 mb-2">
  <div class="card-header"><i class="far fa-calendar-alt"></i> <strong>January, 2027</strong></div>
  <div class="card-body"><ul class="list-unstyled">
    <li>
        Jan 15
<a href="/event/icbf-2027-january-istanbul-tr" title="International Conference on Business and Finance (ICBF)">International Conference on Business and Finance (ICBF)</a> - Istanbul, Turkey      </li>
  </ul></div>
</div>
</div>
"""

# Page 2: everything is far past the window -> paging must stop early.
PAGE_2 = """
<div class="card card-year card-year-2028 mb-2">
  <div class="card-header"><strong>March, 2028</strong></div>
  <div class="card-body"><ul class="list-unstyled">
    <li> Mar 10 <a href="/event/late-2028-march-izmir-tr" title="Late Conf">Late Conf</a> - Izmir, Turkey </li>
  </ul></div>
</div>
"""


class ParseListingTest(unittest.TestCase):
    def test_parses_real_markup(self):
        recs = seminars.parse_listing(PAGE_1, "TR")
        self.assertEqual(len(recs), 3)
        first = recs[0]
        self.assertEqual(first.start_date, date(2026, 7, 29))
        self.assertEqual(first.start_date, first.end_date)          # single-day
        self.assertEqual(first.city, "Istanbul")
        self.assertEqual(first.category, "seminar")
        self.assertEqual(first.source, "seminars")
        self.assertIn("ICMAMS", first.event)
        self.assertEqual(first.raw["source_site"], "conferenceindex")
        self.assertTrue(first.raw["url"].startswith("https://conferenceindex.org/event/"))

    def test_year_comes_from_each_card_header(self):
        recs = {r.event.split("(")[0].strip(): r for r in seminars.parse_listing(PAGE_1, "TR")}
        # The 3rd row lives in the "January, 2027" card -> 2027, not the 2026 card above it.
        icbf = next(r for k, r in recs.items() if "Finance" in k)
        self.assertEqual(icbf.start_date, date(2027, 1, 15))

    def test_relative_event_href_is_absolutised(self):
        iceb = seminars.parse_listing(PAGE_1, "TR")[1]
        self.assertEqual(iceb.raw["url"], "https://conferenceindex.org/event/iceb-2026-july-antalya-tr")

    def test_no_cards_yields_nothing(self):
        self.assertEqual(seminars.parse_listing("<div>nothing here</div>", "TR"), [])


class FetchWindowTest(unittest.TestCase):
    def test_window_filter_and_early_stop(self):
        get = mock.Mock(side_effect=[PAGE_1, PAGE_2])
        events = seminars.fetch_events_in_window(
            "TR", date(2026, 7, 1), date(2026, 12, 31), pause=0, get=get,
        )
        # Only the two July-2026 conferences fall in the window; Jan-2027 is out.
        self.assertEqual({e.start_date for e in events}, {date(2026, 7, 29), date(2026, 7, 30)})
        self.assertEqual(len(events), 2)
        # Page 2 is entirely past the window end -> paging stops there (2 fetches).
        self.assertEqual(get.call_count, 2)

    def test_unmapped_country_is_skipped_without_fetching(self):
        get = mock.Mock(side_effect=AssertionError("should not fetch"))
        self.assertEqual(seminars.fetch_events_in_window("XX", date(2026, 1, 1), date(2026, 12, 31), get=get), [])
        get.assert_not_called()

    def test_paced_url_uses_page_query(self):
        get = mock.Mock(side_effect=[PAGE_1, PAGE_2])
        seminars.fetch_events_in_window("TR", date(2026, 1, 1), date(2026, 12, 31), pause=0, get=get)
        called = [c.args[0] for c in get.call_args_list]
        self.assertEqual(called[0], "https://conferenceindex.org/conferences/business/turkey")
        self.assertEqual(called[1], "https://conferenceindex.org/conferences/business/turkey?page=2")


if __name__ == "__main__":
    unittest.main()

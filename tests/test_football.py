import unittest
from datetime import date
from unittest import mock

from special_days.sources import football

FIXTURE_FULL = {
    "fixture": {
        "id": 101,
        "date": "2026-08-15T16:00:00+00:00",
        "venue": {"id": 9, "name": "Rams Park", "city": "Istanbul"},
        "status": {"short": "NS"},
    },
    "league": {"id": 203, "name": "Süper Lig", "country": "Turkey", "season": 2026},
    "teams": {
        "home": {"id": 645, "name": "Galatasaray"},
        "away": {"id": 611, "name": "Fenerbahçe"},
    },
}
FIXTURE_UEFA = {
    "fixture": {"id": 202, "date": "2026-05-30T19:00:00+00:00", "venue": {"city": "Munich"}},
    "league": {"id": 2, "name": "UEFA Champions League", "country": "World", "season": 2025},
    "teams": {"home": {"name": "Real Madrid"}, "away": {"name": "Liverpool"}},
}
FIXTURE_NO_TEAMS = {
    "fixture": {"id": 303, "date": "2026-09-01T18:00:00+00:00", "venue": {"city": "Leeds"}},
    "league": {"id": 39, "country": "England"},
    "teams": {"home": {"name": "Leeds"}},  # away missing -> skip
}
FIXTURE_BAD_DATE = {
    "fixture": {"id": 404, "date": "not-a-date", "venue": {"city": "X"}},
    "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
}
FIXTURE_NO_VENUE = {
    "fixture": {"id": 505, "date": "2026-10-10T15:00:00+00:00"},
    "league": {"id": 39, "country": "England"},
    "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
}
FIXTURE_FULL_2 = {
    "fixture": {"id": 102, "date": "2026-08-22T16:00:00+00:00", "venue": {"city": "Istanbul"}},
    "league": {"id": 203, "country": "Turkey"},
    "teams": {"home": {"name": "Beşiktaş"}, "away": {"name": "Trabzonspor"}},
}
FIXTURE_PORTUGAL = {  # country not in the mapping table
    "fixture": {"id": 606, "date": "2026-09-20T18:00:00+00:00", "venue": {"city": "Porto"}},
    "league": {"id": 94, "country": "Portugal"},
    "teams": {"home": {"name": "Porto"}, "away": {"name": "Benfica"}},
}
FIXTURE_NO_COUNTRY = {  # league carries no country at all
    "fixture": {"id": 707, "date": "2026-09-21T18:00:00+00:00", "venue": {"city": "Nowhere"}},
    "league": {"id": 0},
    "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
}
FIXTURE_IDLESS = {  # well-formed teams + date but no fixture id
    "fixture": {"date": "2026-08-20T18:00:00+00:00", "venue": {"city": "Ankara"}},
    "league": {"id": 203, "country": "Turkey"},
    "teams": {"home": {"name": "X"}, "away": {"name": "Y"}},
}


def _response(*fixtures):
    return {"get": "fixtures", "errors": [], "results": len(fixtures), "response": list(fixtures)}


def _page(fixtures, current, total):
    data = _response(*fixtures)
    data["paging"] = {"current": current, "total": total}
    return data


class ParseFixtureTest(unittest.TestCase):
    def test_full_fixture(self):
        sd = football._parse_fixture(FIXTURE_FULL)
        self.assertEqual(sd.event, "Galatasaray vs Fenerbahçe")
        self.assertEqual(sd.start_date, date(2026, 8, 15))
        self.assertEqual(sd.end_date, sd.start_date)  # single-day
        self.assertEqual(sd.city, "Istanbul")
        self.assertEqual(sd.category, "sports")
        self.assertEqual(sd.country, "TR")
        self.assertEqual(sd.source, "football")
        self.assertIsNone(sd.lat)  # API-Football has no coords
        self.assertIsNone(sd.lon)
        self.assertIs(sd.raw, FIXTURE_FULL)

    def test_uefa_world_country_maps_to_int(self):
        self.assertEqual(football._parse_fixture(FIXTURE_UEFA).country, "INT")

    def test_england_maps_to_gb(self):
        sd = football._parse_fixture(FIXTURE_NO_VENUE)
        self.assertEqual(sd.country, "GB")

    def test_datetime_is_truncated_to_date(self):
        self.assertEqual(football._parse_fixture(FIXTURE_UEFA).start_date, date(2026, 5, 30))

    def test_missing_team_is_skipped(self):
        self.assertIsNone(football._parse_fixture(FIXTURE_NO_TEAMS))

    def test_bad_date_is_skipped(self):
        self.assertIsNone(football._parse_fixture(FIXTURE_BAD_DATE))

    def test_missing_venue_city_is_unknown(self):
        self.assertEqual(football._parse_fixture(FIXTURE_NO_VENUE).city, "Unknown")

    def test_unmapped_country_is_blank(self):
        # no guessing from the name (Portugal must NOT become "PO")
        self.assertEqual(football._parse_fixture(FIXTURE_PORTUGAL).country, "")

    def test_missing_country_is_blank(self):
        self.assertEqual(football._parse_fixture(FIXTURE_NO_COUNTRY).country, "")


class SeasonHelperTest(unittest.TestCase):
    def test_season_of_uses_august_boundary(self):
        self.assertEqual(football._season_of(date(2026, 8, 1)), 2026)
        self.assertEqual(football._season_of(date(2026, 7, 1)), 2026)
        self.assertEqual(football._season_of(date(2026, 6, 30)), 2025)
        self.assertEqual(football._season_of(date(2026, 1, 5)), 2025)

    def test_seasons_for_window_single(self):
        self.assertEqual(
            football._seasons_for_window(date(2026, 9, 1), date(2026, 12, 31)), [2026]
        )

    def test_seasons_for_window_crosses_boundary(self):
        # June 2026 -> season 2025; September 2026 -> season 2026.
        self.assertEqual(
            football._seasons_for_window(date(2026, 6, 1), date(2026, 9, 1)), [2025, 2026]
        )


class FetchFixturesTest(unittest.TestCase):
    def test_maps_and_filters_to_window(self):
        out_of_window = {
            "fixture": {"id": 999, "date": "2030-01-01T12:00:00+00:00", "venue": {"city": "X"}},
            "league": {"id": 203, "country": "Turkey"},
            "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
        }
        with mock.patch(
            "special_days.sources.football.get_json",
            return_value=_response(FIXTURE_FULL, out_of_window),
        ):
            rows = football.fetch_fixtures_in_window(
                203, "KEY", date(2026, 8, 1), date(2026, 8, 31)
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].event, "Galatasaray vs Fenerbahçe")

    def test_passes_apisports_header_and_query_params(self):
        with mock.patch(
            "special_days.sources.football.get_json", return_value=_response(FIXTURE_FULL)
        ) as get_json:
            football.fetch_fixtures_in_window(203, "SECRET", date(2026, 8, 1), date(2026, 8, 31))
        kwargs = get_json.call_args.kwargs
        self.assertEqual(kwargs["headers"], {"x-apisports-key": "SECRET"})
        params = kwargs["params"]
        self.assertEqual(params["league"], 203)
        self.assertEqual(params["season"], 2026)
        self.assertEqual(params["from"], "2026-08-01")
        self.assertEqual(params["to"], "2026-08-31")
        self.assertEqual(params["page"], 1)

    def test_queries_each_season_the_window_touches(self):
        with mock.patch(
            "special_days.sources.football.get_json", return_value=_response()
        ) as get_json:
            football.fetch_fixtures_in_window(203, "KEY", date(2026, 6, 1), date(2026, 9, 1))
        self.assertEqual(get_json.call_count, 2)  # season 2025 + 2026
        self.assertEqual([c.kwargs["params"]["season"] for c in get_json.call_args_list], [2025, 2026])

    def test_dedupes_same_fixture_across_seasons(self):
        # The same fixture id returned under both season queries -> one row.
        with mock.patch(
            "special_days.sources.football.get_json", return_value=_response(FIXTURE_FULL)
        ):
            rows = football.fetch_fixtures_in_window(
                203, "KEY", date(2026, 6, 1), date(2026, 9, 1)
            )
        self.assertEqual(len(rows), 1)

    def test_skips_malformed_keeps_good(self):
        with mock.patch(
            "special_days.sources.football.get_json",
            return_value=_response(FIXTURE_BAD_DATE, FIXTURE_FULL),
        ):
            rows = football.fetch_fixtures_in_window(
                203, "KEY", date(2026, 8, 1), date(2026, 8, 31)
            )
        self.assertEqual(len(rows), 1)

    def test_empty_response(self):
        with mock.patch(
            "special_days.sources.football.get_json", return_value=_response()
        ):
            rows = football.fetch_fixtures_in_window(
                203, "KEY", date(2026, 9, 1), date(2026, 12, 31)
            )
        self.assertEqual(rows, [])

    def test_pages_through_all_pages(self):
        pages = [_page([FIXTURE_FULL], 1, 2), _page([FIXTURE_FULL_2], 2, 2)]
        with mock.patch(
            "special_days.sources.football.get_json", side_effect=pages
        ) as get_json:
            rows = football.fetch_fixtures_in_window(
                203, "KEY", date(2026, 8, 1), date(2026, 8, 31)
            )
        self.assertEqual(get_json.call_count, 2)  # both pages fetched
        self.assertEqual(
            {r.event for r in rows},
            {"Galatasaray vs Fenerbahçe", "Beşiktaş vs Trabzonspor"},
        )
        self.assertEqual([c.kwargs["params"]["page"] for c in get_json.call_args_list], [1, 2])

    def test_stops_paging_when_current_reaches_total(self):
        # current == total == 1 -> exactly one request even with rows present
        with mock.patch(
            "special_days.sources.football.get_json", return_value=_page([FIXTURE_FULL], 1, 1)
        ) as get_json:
            football.fetch_fixtures_in_window(203, "KEY", date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(get_json.call_count, 1)

    def test_dedupes_idless_fixture_across_seasons(self):
        # id-less fixture echoed under both season queries -> one row (event+date key)
        with mock.patch(
            "special_days.sources.football.get_json", return_value=_response(FIXTURE_IDLESS)
        ):
            rows = football.fetch_fixtures_in_window(
                203, "KEY", date(2026, 6, 1), date(2026, 9, 1)
            )
        self.assertEqual(len(rows), 1)

    def test_errors_in_body_degrade_gracefully(self):
        bad = {"errors": {"token": "invalid"}, "response": []}
        with mock.patch("special_days.sources.football.get_json", return_value=bad):
            rows = football.fetch_fixtures_in_window(
                203, "KEY", date(2026, 9, 1), date(2026, 12, 31)
            )
        self.assertEqual(rows, [])  # populated errors must not raise

    def test_multi_season_window_filters_out_of_window_fixture(self):
        before_window = {
            "fixture": {"id": 900, "date": "2026-05-30T18:00:00+00:00", "venue": {"city": "X"}},
            "league": {"id": 203, "country": "Turkey"},
            "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
        }
        # Window crosses the season boundary -> 2 season queries; the 2026-05-30
        # fixture is before start and must be filtered out of both.
        with mock.patch(
            "special_days.sources.football.get_json",
            return_value=_response(before_window, FIXTURE_FULL),
        ):
            rows = football.fetch_fixtures_in_window(
                203, "KEY", date(2026, 6, 1), date(2026, 9, 1)
            )
        self.assertEqual([r.event for r in rows], ["Galatasaray vs Fenerbahçe"])


if __name__ == "__main__":
    unittest.main()

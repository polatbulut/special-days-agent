import unittest
from datetime import date
from unittest import mock

from special_days import agents
from special_days.models import SpecialDate
from special_days.sources import football


def _fx(event="A vs B"):
    return SpecialDate(event, date(2026, 8, 15), date(2026, 8, 15),
                       "City", "sports", "TR", "football")


class FootballLeaguesTest(unittest.TestCase):
    def test_turkey_pulls_super_lig_only(self):
        self.assertEqual(agents.TurkeyAgent(football_key="K")._football_leagues(), [football.SUPER_LIG])

    def test_international_top_leagues_plus_uefa_once(self):
        a = agents.InternationalAgent(countries=["GB", "DE"], football_key="K")
        leagues = a._football_leagues()
        self.assertIn(football.TOP_LEAGUE_BY_COUNTRY["GB"], leagues)
        self.assertIn(football.TOP_LEAGUE_BY_COUNTRY["DE"], leagues)
        for uefa in football.UEFA_LEAGUES:
            self.assertEqual(leagues.count(uefa), 1)  # UEFA appended exactly once

    def test_unmapped_country_skipped_without_error(self):
        # US has no mapping -> only UEFA leagues remain
        a = agents.InternationalAgent(countries=["US"], football_key="K")
        self.assertEqual(a._football_leagues(), list(football.UEFA_LEAGUES))

    def test_duplicate_country_deduped(self):
        base = agents.Agent("x", ["GB", "GB"], football_key="K")._football_leagues()
        self.assertEqual(base, [football.TOP_LEAGUE_BY_COUNTRY["GB"]])


class CollectFootballTest(unittest.TestCase):
    def test_skips_football_when_no_key(self):
        a = agents.TurkeyAgent(football_key="")  # falsy key
        with mock.patch("special_days.sources.football.fetch_fixtures_in_window") as fetch:
            out = a._collect_football(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(out, [])
        fetch.assert_not_called()  # gated, no network

    def test_collects_super_lig_when_key_present(self):
        a = agents.TurkeyAgent(football_key="K")
        with mock.patch(
            "special_days.sources.football.fetch_fixtures_in_window", return_value=[_fx()]
        ) as fetch:
            out = a._collect_football(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(len(out), 1)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0], football.SUPER_LIG)  # league id

    def test_one_failing_league_does_not_abort_others(self):
        a = agents.InternationalAgent(countries=["GB", "DE"], football_key="K")

        def flaky(league, key, start, end, **kw):
            if league == football.TOP_LEAGUE_BY_COUNTRY["GB"]:
                raise RuntimeError("boom")
            return [_fx(f"L{league}")]

        with mock.patch("special_days.sources.football.fetch_fixtures_in_window", side_effect=flaky):
            out = a._collect_football(date(2026, 8, 1), date(2026, 8, 31))
        # GB raised; the remaining leagues (DE + UEFA) still collected
        self.assertGreaterEqual(len(out), 1)
        self.assertTrue(all(isinstance(x, SpecialDate) for x in out))

    def test_collect_excludes_football_when_include_events_false(self):
        a = agents.TurkeyAgent(football_key="K")
        with mock.patch.object(a, "_collect_football", return_value=[_fx()]) as cf, \
                mock.patch("special_days.sources.nager.fetch_holidays_in_window", return_value=[]), \
                mock.patch("special_days.sources.diyanet.fetch_in_window", return_value=[]), \
                mock.patch("special_days.sources.meb.fetch_in_window", return_value=[]):
            a.collect(date(2026, 8, 1), date(2026, 8, 31), include_holidays=True, include_events=False)
        cf.assert_not_called()


class CollectCountryEventsTest(unittest.TestCase):
    """The country-keyed event sources (ticketmaster, eventseye) are each gated."""

    def _run(self, **kw):
        a = agents.Agent("x", ["TR"], **kw)
        out: list = []
        a._collect_events_for_country("TR", date(2026, 8, 1), date(2026, 8, 31), out)
        return out

    def test_eventseye_skipped_by_default(self):
        with mock.patch("special_days.sources.eventseye.fetch_events_in_window") as fetch:
            self._run(eventseye=False)
        fetch.assert_not_called()  # opt-in, no network

    def test_eventseye_called_when_enabled(self):
        with mock.patch(
            "special_days.sources.eventseye.fetch_events_in_window", return_value=[_fx()]
        ) as fetch:
            out = self._run(eventseye=True)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0], "TR")
        self.assertEqual(len(out), 1)

    def test_one_failing_source_does_not_abort_others(self):
        # ticketmaster raises; eventseye still runs and its rows survive.
        with mock.patch(
            "special_days.sources.ticketmaster.fetch_events", side_effect=RuntimeError("boom")
        ), mock.patch(
            "special_days.sources.eventseye.fetch_events_in_window", return_value=[_fx()]
        ) as eye:
            out = self._run(ticketmaster_key="K", eventseye=True)
        eye.assert_called_once()  # ticketmaster raised, eventseye still ran
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()

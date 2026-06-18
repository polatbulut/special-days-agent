import unittest
from datetime import date
from unittest import mock

from special_days import agents, cli
from special_days.models import SpecialDate


def holiday(name, country):
    day = date(2026, 1, 1)
    return SpecialDate(name, day, day, f"Nationwide ({country})", "holiday", country, "nager")


class CollectTest(unittest.TestCase):
    def test_deduplicates_overlapping_agents(self):
        # Both agents collect TR -> identical TR rows must collapse to one.
        def fake_collect(self, year, include_holidays=True, include_events=True):
            country = self.countries[0]
            return [holiday("Yılbaşı", country)]

        args = cli.build_parser().parse_args(
            ["--agent", "both", "--countries", "TR", "--source", "holidays"]
        )
        with mock.patch.object(agents.Agent, "collect", fake_collect):
            rows = cli.collect(args)
        self.assertEqual(len(rows), 1)

    def test_negative_limit_is_rejected(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--limit", "-3"])


if __name__ == "__main__":
    unittest.main()

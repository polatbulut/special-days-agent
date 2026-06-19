import os
import tempfile
import unittest
from datetime import date
from unittest import mock

from special_days import agents, cli
from special_days.models import SpecialDate


def holiday(name, country):
    day = date(2026, 1, 1)
    return SpecialDate(name, day, day, f"Nationwide ({country})", "public_holiday", country, "nager")


class CollectTest(unittest.TestCase):
    def test_deduplicates_overlapping_agents(self):
        # Both agents collect TR -> identical TR rows must collapse to one.
        def fake_collect(self, start, end, include_holidays=True, include_events=True):
            country = self.countries[0]
            return [holiday("Yılbaşı", country)]

        args = cli.build_parser().parse_args(
            ["--agent", "both", "--countries", "TR", "--source", "holidays"]
        )
        with mock.patch.object(agents.Agent, "collect", fake_collect), \
                mock.patch("special_days.sources.diyanet.fetch_in_window", return_value=[]), \
                mock.patch("special_days.sources.meb.fetch_in_window", return_value=[]):
            rows = cli.collect(args, date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(rows), 1)

    def test_negative_limit_is_rejected(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--limit", "-3"])

    def test_zero_months_is_rejected(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--months", "0"])

    def test_bad_start_date_is_rejected(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--start", "not-a-date"])

    def test_concurrency_must_be_positive(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--concurrency", "0"])


class ResolveFormatTest(unittest.TestCase):
    def _args(self, argv):
        return cli.build_parser().parse_args(argv)

    def test_infers_format_from_extension(self):
        self.assertEqual(cli._resolve_format(self._args(["-o", "out/feed.xlsx"])), "xlsx")
        self.assertEqual(cli._resolve_format(self._args(["-o", "x.csv"])), "csv")
        self.assertEqual(cli._resolve_format(self._args(["-o", "x.json"])), "json")

    def test_unknown_extension_defaults_to_table(self):
        self.assertEqual(cli._resolve_format(self._args(["-o", "x.txt"])), "table")

    def test_explicit_format_wins_over_extension(self):
        self.assertEqual(cli._resolve_format(self._args(["--format", "csv", "-o", "x.xlsx"])), "csv")

    def test_no_output_defaults_to_table(self):
        self.assertEqual(cli._resolve_format(self._args([])), "table")

    def test_impact_scorer_choice_validated(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--impact-scorer", "bogus"])

    def test_openai_scorer_without_key_errors_cleanly(self):
        # get_scorer("openai") raises before any collection runs -> exit 2, no network.
        with mock.patch("special_days.cli.get_openai_key", return_value=None):
            rc = cli.main(["--agent", "turkey", "--source", "holidays", "--impact-scorer", "openai"])
        self.assertEqual(rc, 2)

    def test_vllm_scorer_without_base_url_errors_cleanly(self):
        with mock.patch("special_days.cli.get_vllm_base_url", return_value=None):
            rc = cli.main(["--agent", "turkey", "--source", "holidays", "--impact-scorer", "vllm"])
        self.assertEqual(rc, 2)

    def test_output_creates_missing_parent_dirs(self):
        rows = [holiday("Yılbaşı", "TR")]
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "nested", "dir", "feed.csv")
            argv = ["--agent", "turkey", "--source", "holidays", "--format", "csv", "-o", out]
            with mock.patch("special_days.cli.collect", return_value=rows):
                cli.main(argv)
            self.assertTrue(os.path.isfile(out))


if __name__ == "__main__":
    unittest.main()

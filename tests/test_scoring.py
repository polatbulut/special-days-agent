import unittest
from datetime import date

from special_days import scoring
from special_days.models import SpecialDate


def holiday(category="religious_holiday", source="diyanet", country="TR", start="2027-03-08", end="2027-03-11"):
    return SpecialDate("H", date.fromisoformat(start), date.fromisoformat(end),
                       "Nationwide (TR)", category, country, source)


def event(category="concert", distance=None, lat=41.0, lon=29.0):
    return SpecialDate("E", date(2026, 7, 1), date(2026, 7, 1), "İstanbul",
                       category, "TR", "ticketmaster", lat=lat, lon=lon,
                       nearest_airport="IST" if distance is not None else None,
                       airport_distance_km=distance)


class HeuristicScorerTest(unittest.TestCase):
    def setUp(self):
        self.scorer = scoring.HeuristicScorer()

    def test_returns_int_0_100(self):
        s = self.scorer.score(holiday())
        self.assertIsInstance(s, int)
        self.assertTrue(0 <= s <= 100)

    def test_religious_outranks_concert(self):
        self.assertGreater(self.scorer.score(holiday()), self.scorer.score(event()))

    def test_close_airport_boosts(self):
        self.assertGreater(
            self.scorer.score(event(distance=10)), self.scorer.score(event(distance=None))
        )


class LLMScorerTest(unittest.TestCase):
    def test_scenario_routing(self):
        s = scoring.LLMScorer(lambda p: "50")
        self.assertEqual(s._scenario(holiday()), "tr_holiday")
        self.assertEqual(s._scenario(holiday(source="nager", country="DE")), "intl_holiday")
        self.assertEqual(s._scenario(event()), "event")

    def test_prompt_differs_by_scenario(self):
        s = scoring.LLMScorer(lambda p: "50")
        self.assertNotEqual(s._build_prompt(holiday()), s._build_prompt(event()))
        self.assertIn("Turkish", s._build_prompt(holiday()))

    def test_injected_model_is_used_and_parsed(self):
        calls = []

        def fake(prompt):
            calls.append(prompt)
            return "Based on the details, I rate this 87"

        self.assertEqual(scoring.LLMScorer(fake).score(holiday()), 87)
        self.assertEqual(len(calls), 1)
        self.assertIn("0-100", calls[0])  # the built prompt was passed through

    def test_parse_bare_integer(self):
        self.assertEqual(scoring.LLMScorer(lambda p: "87").score(holiday()), 87)

    def test_parse_ignores_year_in_reply(self):
        self.assertEqual(scoring.LLMScorer(lambda p: "In 2026 I rate this 90").score(holiday()), 90)
        self.assertEqual(scoring.LLMScorer(lambda p: "For 2026-01-01: 85").score(holiday()), 85)

    def test_parse_clamps(self):
        self.assertEqual(scoring.LLMScorer(lambda p: "250").score(holiday()), 100)

    def test_parse_raises_on_no_number(self):
        with self.assertRaises(ValueError):
            scoring.LLMScorer(lambda p: "n/a").score(holiday())


class GetScorerTest(unittest.TestCase):
    def test_default_heuristic(self):
        self.assertIsInstance(scoring.get_scorer("heuristic"), scoring.HeuristicScorer)

    def test_openai_requires_key(self):
        with self.assertRaises(ValueError):
            scoring.get_scorer("openai", openai_api_key=None)

    def test_openai_builds_llm_scorer(self):
        self.assertIsInstance(scoring.get_scorer("openai", openai_api_key="sk-x"), scoring.LLMScorer)

    def test_vllm_requires_base_url(self):
        with self.assertRaises(ValueError):
            scoring.get_scorer("vllm", vllm_base_url=None, model="m")

    def test_vllm_requires_model(self):
        with self.assertRaises(ValueError):
            scoring.get_scorer("vllm", vllm_base_url="http://x:8000/v1", model=None)

    def test_vllm_builds_llm_scorer(self):
        s = scoring.get_scorer("vllm", vllm_base_url="http://x:8000/v1", model="my-model")
        self.assertIsInstance(s, scoring.LLMScorer)

    def test_unknown_scorer(self):
        with self.assertRaises(ValueError):
            scoring.get_scorer("nope")


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date

from special_days import scoring
from special_days.models import SpecialDate


def holiday(category="religious_holiday", source="diyanet", country="TR", start="2027-03-08", end="2027-03-11"):
    return SpecialDate("H", date.fromisoformat(start), date.fromisoformat(end),
                       "Nationwide (TR)", category, country, source)


def event(category="concert", distance=None, lat=41.0, lon=29.0, raw=None):
    return SpecialDate("E", date(2026, 7, 1), date(2026, 7, 1), "İstanbul",
                       category, "TR", "ticketmaster", lat=lat, lon=lon,
                       nearest_airport="IST" if distance is not None else None,
                       airport_distance_km=distance, raw=raw or {"name": "E", "id": "abc"})


def football(raw=None):
    return SpecialDate("Galatasaray vs Fenerbahçe", date(2026, 8, 15), date(2026, 8, 15),
                       "İstanbul", "sports", "TR", "football",
                       raw=raw or {"teams": {"home": {"name": "GS"}, "away": {"name": "FB"}}})


class HeuristicScorerTest(unittest.TestCase):
    def setUp(self):
        self.scorer = scoring.HeuristicScorer()

    def test_returns_score_result_int_impact_no_attendance(self):
        r = self.scorer.score(holiday())
        self.assertIsInstance(r, scoring.ScoreResult)
        self.assertIsInstance(r.impact, int)
        self.assertTrue(0 <= r.impact <= 100)
        self.assertIsNone(r.attendance)  # heuristic never predicts attendance

    def test_religious_outranks_concert(self):
        self.assertGreater(self.scorer.score(holiday()).impact, self.scorer.score(event()).impact)

    def test_close_airport_boosts(self):
        self.assertGreater(
            self.scorer.score(event(distance=10)).impact,
            self.scorer.score(event(distance=None)).impact,
        )


class PromptRoutingTest(unittest.TestCase):
    def setUp(self):
        self.scorer = scoring.LLMScorer(lambda p: '{"impact": 50}')

    def test_per_source_prompts_all_differ(self):
        prompts = [self.scorer._build_prompt(holiday(source=s)) for s in ("nager", "diyanet", "meb")]
        prompts.append(self.scorer._build_prompt(event()))
        prompts.append(self.scorer._build_prompt(football()))
        self.assertEqual(len(set(prompts)), 5)

    def test_ticketmaster_prompt_embeds_payload_and_asks_attendance(self):
        p = self.scorer._build_prompt(event(raw={"name": "Tarkan", "id": "XYZ123"}))
        self.assertIn("XYZ123", p)  # full payload embedded
        self.assertIn("attendance", p.lower())

    def test_football_prompt_embeds_payload_and_asks_attendance(self):
        p = self.scorer._build_prompt(football(raw={"id": "FX99", "teams": {}}))
        self.assertIn("FX99", p)  # full payload embedded
        self.assertIn("attendance", p.lower())
        # football-specific framing, so a misroute to the ticketmaster builder fails
        self.assertIn("football fixture", p)
        self.assertNotIn("ticketed event", p)

    def test_holiday_prompt_is_impact_only_and_mentions_thy(self):
        p = self.scorer._build_prompt(holiday(source="nager", country="DE"))
        self.assertIn("Turkish Airlines", p)
        self.assertNotIn("attendance", p.lower())

    def test_eventseye_prompt_embeds_payload_and_asks_attendance(self):
        ev = SpecialDate("Trade Fair", date(2026, 5, 1), date(2026, 5, 3), "İstanbul",
                         "expo", "TR", "eventseye", raw={"name": "Trade Fair", "sector": "MINING-XYZ"})
        pe = self.scorer._build_prompt(ev)
        self.assertIn("MINING-XYZ", pe)        # full payload embedded
        self.assertIn("attendance", pe.lower())
        self.assertIn("trade fair", pe.lower())  # eventseye-specific framing
        # distinct from the ticketmaster builder it must not fall back to
        self.assertNotEqual(pe, self.scorer._build_prompt(event()))


class LLMScoreTest(unittest.TestCase):
    def test_event_returns_attendance_and_impact(self):
        r = scoring.LLMScorer(lambda p: '{"attendance": 8000, "impact": 70}').score(event())
        self.assertEqual((r.impact, r.attendance), (70, 8000))

    def test_football_event_keeps_attendance(self):
        # football is an event source -> attendance survives like ticketmaster
        r = scoring.LLMScorer(lambda p: '{"attendance": 41000, "impact": 25}').score(football())
        self.assertEqual((r.impact, r.attendance), (25, 41000))

    def test_eventseye_keeps_attendance(self):
        # eventseye is an event source -> attendance survives like ticketmaster
        ev = SpecialDate("F", date(2026, 5, 1), date(2026, 5, 3), "X", "expo", "TR", "eventseye",
                         raw={"name": "F"})
        r = scoring.LLMScorer(lambda p: '{"attendance": 12000, "impact": 30}').score(ev)
        self.assertEqual((r.impact, r.attendance), (30, 12000))

    def test_holiday_attendance_forced_none(self):
        # even if the model returns an attendance, holidays must stay null
        r = scoring.LLMScorer(lambda p: '{"attendance": 999, "impact": 60}').score(
            holiday(source="nager", country="DE")
        )
        self.assertEqual(r.impact, 60)
        self.assertIsNone(r.attendance)

    def test_code_fenced_json(self):
        r = scoring.LLMScorer(lambda p: '```json\n{"attendance": 5000, "impact": 42}\n```').score(event())
        self.assertEqual((r.impact, r.attendance), (42, 5000))

    def test_impact_clamped(self):
        self.assertEqual(scoring.LLMScorer(lambda p: '{"impact": 250}').score(event()).impact, 100)

    def test_fallback_bare_integer(self):
        self.assertEqual(scoring.LLMScorer(lambda p: "87").score(event()).impact, 87)

    def test_fallback_ignores_year_in_reply(self):
        self.assertEqual(scoring.LLMScorer(lambda p: "In 2026 I rate this 90").score(event()).impact, 90)

    def test_raises_on_no_number(self):
        with self.assertRaises(ValueError):
            scoring.LLMScorer(lambda p: "n/a").score(event())


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

    def test_azure_requires_endpoint(self):
        with self.assertRaises(ValueError):
            scoring.get_scorer("azure", azure_endpoint=None, azure_api_key="k", model="dep")

    def test_azure_requires_key(self):
        with self.assertRaises(ValueError):
            scoring.get_scorer(
                "azure", azure_endpoint="https://x.openai.azure.com", azure_api_key=None, model="dep"
            )

    def test_azure_builds_llm_scorer(self):
        s = scoring.get_scorer(
            "azure", azure_endpoint="https://x.openai.azure.com", azure_api_key="k", model="dep"
        )
        self.assertIsInstance(s, scoring.LLMScorer)

    def test_unknown_scorer(self):
        with self.assertRaises(ValueError):
            scoring.get_scorer("nope")


if __name__ == "__main__":
    unittest.main()

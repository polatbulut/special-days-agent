import unittest
from datetime import date

from special_days.dataset import load_airports, load_diyanet, load_meb


class AirportDataTest(unittest.TestCase):
    def test_airports_well_formed_and_unique(self):
        airports = load_airports()
        self.assertGreater(len(airports), 20)
        seen = set()
        for a in airports:
            self.assertRegex(a["iata"], r"^[A-Z]{3}$")
            self.assertNotIn(a["iata"], seen)
            seen.add(a["iata"])
            self.assertTrue(-90 <= a["lat"] <= 90)
            self.assertTrue(-180 <= a["lon"] <= 180)
            self.assertTrue(a["city"] and a["country"])


class HolidayDataTest(unittest.TestCase):
    def _check_ranges(self, records):
        self.assertGreater(len(records), 0)
        for r in records:
            self.assertTrue(r["name"].strip())
            start = date.fromisoformat(r["start"])
            end = date.fromisoformat(r["end"])
            self.assertLessEqual(start, end, f"{r['name']} {r['start']}..{r['end']}")

    def test_diyanet_dates_valid(self):
        self._check_ranges(load_diyanet())

    def test_meb_dates_valid(self):
        self._check_ranges(load_meb())


if __name__ == "__main__":
    unittest.main()

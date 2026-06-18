import unittest

from src.pnr_service import retrieval


class RetrievalTest(unittest.TestCase):
    def test_flight_search_shortlist(self):
        self.assertEqual(["flight_search_roundtrip"], retrieval.intent_shortlist("大后天上午内蒙去西藏第二天下午回"))

    def test_extract_locations(self):
        locations = retrieval.extract_locations("北京到成都中转上海")
        self.assertEqual(["PEK", "CTU", "SHA"], [item["code"] for item in locations])

    def test_retrieve_hints(self):
        context = retrieval.retrieve("下个月23号13点50北京到成都中转上海东航", ["flight_search_oneway"])
        self.assertEqual("PEK", context["hints"]["departure_code"])
        self.assertEqual("CTU", context["hints"]["arrival_code"])
        self.assertEqual("1350", context["hints"]["departure_time"])
        self.assertEqual("MU", context["hints"]["airline"])


if __name__ == "__main__":
    unittest.main()


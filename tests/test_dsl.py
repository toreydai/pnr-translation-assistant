import unittest

from src.pnr_service import dsl


class DslTest(unittest.TestCase):
    def test_add_ssr_meal_validates_and_renders(self):
        intermediate = {
            "intent": "add_ssr_meal",
            "entities": {
                "passenger_ref": "P1",
                "segment_ref": "S2",
                "ssr_code": "VGML",
                "airline": "MU",
            },
        }
        pnr_context = {"passenger_refs": ["P1"], "segment_refs": ["S2"]}

        self.assertEqual([], dsl.validate(intermediate, pnr_context))
        self.assertEqual("SSR VGML MU HK1/P1/S2", dsl.render(intermediate))
        self.assertTrue(dsl.reverse_parse("SSR VGML MU HK1/P1/S2", intermediate))

    def test_medium_or_high_risk_not_in_auto_schema(self):
        self.assertEqual("low", dsl.get_command("add_ssr_meal").risk_policy.level)
        self.assertEqual("high", dsl.get_command("cancel_segment").risk_policy.level)
        self.assertFalse(dsl.get_command("cancel_segment").risk_policy.auto_execute)

    def test_normalize_drops_unknown_entity_fields(self):
        intermediate = {
            "intent": "add_ssr_meal",
            "entities": {
                "passenger_ref": "P1",
                "segment_ref": "S2",
                "ssr_code": "VGML",
                "airline": "MU",
                "meal_type": "vegetarian",
            },
        }
        normalized = dsl.normalize(intermediate)
        self.assertNotIn("meal_type", normalized["entities"])

    def test_render_oneway_flight_search(self):
        intermediate = {
            "intent": "flight_search_oneway",
            "entities": {
                "departure_code": "PEK",
                "arrival_code": "CTU",
                "departure_date": "23jul26",
                "departure_time": "1350",
                "display_mode": "m",
            },
        }
        self.assertEqual("av:m/PEKCTU/23jul26/1350", dsl.render(intermediate))

    def test_render_roundtrip_flight_search(self):
        intermediate = {
            "intent": "flight_search_roundtrip",
            "entities": {
                "departure_code": "HET",
                "arrival_code": "LXA",
                "departure_date": "19jun26",
                "departure_time": "0600",
                "return_date": "20jun26",
                "return_time": "1200",
            },
        }
        self.assertEqual("av:/HETLXA/19jun26/0600&20jun26/1200", dsl.render(intermediate))

    def test_normalize_flight_airline_dict_to_code(self):
        intermediate = {
            "intent": "flight_search_oneway",
            "entities": {
                "departure_code": "PEK",
                "arrival_code": "SHA",
                "departure_date": "25JUL26",
                "airline": {"code": "MU", "name": "东航"},
            },
        }
        normalized = dsl.normalize(intermediate)
        self.assertEqual("25jul26", normalized["entities"]["departure_date"])
        self.assertEqual("MU", normalized["entities"]["airline"])


if __name__ == "__main__":
    unittest.main()

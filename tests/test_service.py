import unittest
from unittest.mock import patch

from src.pnr_service import service
from src.pnr_service.auth import AuthContext
from src.pnr_service.service import (
    _apply_deterministic_fixes,
    _derive_real_command,
    _merge_retrieval_hints,
)


class ServiceTest(unittest.TestCase):
    def test_derive_real_command_unredacts_phone(self):
        intermediate = {"intent": "add_contact_phone", "entities": {"phone": "PHONE_1"}}
        real = _derive_real_command(intermediate, {"PHONE_1": "13800138000"})
        self.assertEqual("CTCM 13800138000", real)

    def test_derive_real_command_without_mapping_is_plain_render(self):
        intermediate = {
            "intent": "add_ssr_meal",
            "entities": {"passenger_ref": "P1", "segment_ref": "S2", "ssr_code": "VGML", "airline": "MU"},
        }
        self.assertEqual("SSR VGML MU HK1/P1/S2", _derive_real_command(intermediate, {}))

    def test_review_rejects_maker_checker_violation(self):
        ctx = AuthContext(subject="agent-1", tenant_id="default", roles=["reviewer"])
        record = {"status": "manual_review", "created_by": "agent-1"}
        with patch("src.pnr_service.store.get_translation", return_value=record):
            with self.assertRaises(PermissionError):
                service.review({"translation_id": "tr-1"}, ctx, "approved")

    def test_review_approve_moves_to_ready_for_confirm(self):
        ctx = AuthContext(subject="reviewer-1", tenant_id="default", roles=["reviewer"])
        record = {"status": "manual_review", "created_by": "agent-1"}
        with patch("src.pnr_service.store.get_translation", return_value=record), patch(
            "src.pnr_service.store.update_translation_status"
        ) as update:
            result = service.review({"translation_id": "tr-1"}, ctx, "approved")
        self.assertEqual("ready_for_confirm", result["status"])
        update.assert_called_once()
    def test_merge_retrieval_hints_fills_flight_codes(self):
        intermediate = {
            "intent": "flight_search_oneway",
            "entities": {"departure_date": "23jul26"},
        }
        retrieval_context = {
            "hints": {
                "departure_code": "PEK",
                "arrival_code": "CTU",
                "departure_time": "1350",
            }
        }
        merged = _merge_retrieval_hints(intermediate, retrieval_context)
        self.assertEqual("PEK", merged["entities"]["departure_code"])
        self.assertEqual("CTU", merged["entities"]["arrival_code"])
        self.assertEqual("1350", merged["entities"]["departure_time"])

    def test_deterministic_fixes_fill_redacted_phone(self):
        intermediate = {"intent": "add_contact_phone", "confidence": 0.7, "entities": {}}
        fixed = _apply_deterministic_fixes(intermediate, {"PHONE_1": "13800138000"})
        self.assertEqual("PHONE_1", fixed["entities"]["phone"])
        self.assertEqual(0.95, fixed["confidence"])

    def test_deterministic_fixes_make_cancel_high_risk(self):
        intermediate = {"intent": "cancel_segment", "risk_level": "medium", "entities": {"segment_ref": "S2"}}
        fixed = _apply_deterministic_fixes(intermediate, {})
        self.assertEqual("high", fixed["risk_level"])


if __name__ == "__main__":
    unittest.main()

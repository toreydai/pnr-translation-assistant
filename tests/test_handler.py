import json
import unittest
from unittest.mock import patch

from src.pnr_service import handler


class HandlerTest(unittest.TestCase):
    @patch("src.pnr_service.store.put_secure_command", return_value="s3://bucket/secure-commands/tr.json")
    @patch("src.pnr_service.store.save_translation")
    def test_translate_returns_redacted_command_preview(self, _save_translation, _put_secure_command):
        event = {
            "rawPath": "/v1/pnr/translate",
            "requestContext": {
                "http": {"method": "POST"},
                "authorizer": {"jwt": {"claims": {"sub": "agent-1", "cognito:groups": "translator"}}},
            },
            "body": json.dumps(
                {
                    "session_id": "s-001",
                    "pnr_context_id": "ctx-001",
                    "user_text": "给第一个旅客第二段加一个东航素食餐",
                    "pnr_context": {
                        "passenger_refs": ["P1"],
                        "segment_refs": ["S2"],
                        "version": "v1",
                    },
                },
                ensure_ascii=False,
            ),
        }

        response = handler.lambda_handler(event, None)
        body = json.loads(response["body"])

        self.assertEqual(200, response["statusCode"])
        self.assertEqual("add_ssr_meal", body["intent"])
        self.assertEqual("SSR VGML MU HK1/P1/S2", body["command_preview_redacted"])
        self.assertNotIn("command", body)


if __name__ == "__main__":
    unittest.main()


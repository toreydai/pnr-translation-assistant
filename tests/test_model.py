import unittest

from src.pnr_service.model import parse_model_json


class ModelParsingTest(unittest.TestCase):
    def test_parse_plain_json(self):
        self.assertEqual({"ok": True}, parse_model_json('{"ok": true}'))

    def test_parse_fenced_json(self):
        self.assertEqual({"ok": True}, parse_model_json('```json\n{"ok": true}\n```'))

    def test_parse_json_with_prefix(self):
        self.assertEqual({"ok": True}, parse_model_json('结果如下：\n{"ok": true}'))


if __name__ == "__main__":
    unittest.main()

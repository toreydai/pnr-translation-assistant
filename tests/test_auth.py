import unittest

from src.pnr_service.auth import from_event, require_any_role


class AuthTest(unittest.TestCase):
    def test_no_claims_yields_no_roles(self):
        ctx = from_event({"requestContext": {}})
        self.assertEqual([], ctx.roles)

    def test_missing_role_is_denied(self):
        ctx = from_event({"requestContext": {}})
        with self.assertRaises(PermissionError):
            require_any_role(ctx, ["translator", "executor"])

    def test_cognito_groups_claim_parsed(self):
        event = {
            "requestContext": {
                "authorizer": {"jwt": {"claims": {"sub": "u1", "cognito:groups": "translator,executor"}}}
            }
        }
        ctx = from_event(event)
        self.assertIn("translator", ctx.roles)
        self.assertIn("executor", ctx.roles)
        self.assertEqual("u1", ctx.subject)


if __name__ == "__main__":
    unittest.main()

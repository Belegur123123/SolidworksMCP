import unittest

from solidworks_mcp.automation import SolidWorksAutomation
from solidworks_mcp.automation.transactions_semantic import TransactionOperations


class SemanticIdentityTransactionTests(unittest.TestCase):
    def test_semantic_identity_operations_are_plan_whitelisted(self):
        for name in (
                "register_body_identity", "resolve_body_identity",
                "list_body_identities", "semantic_extrude", "semantic_cut"):
            self.assertIn(name, TransactionOperations.PLAN_OPERATIONS)
            self.assertIn(name, SolidWorksAutomation.PLAN_OPERATIONS)

    def test_existing_transaction_operations_remain_available(self):
        for name in ("advanced_extrude", "advanced_cut",
                     "create_parametric_sketch", "save_document"):
            self.assertIn(name, TransactionOperations.PLAN_OPERATIONS)
            self.assertIn(name, SolidWorksAutomation.PLAN_OPERATIONS)

    def test_automation_exposes_semantic_identity_methods(self):
        for name in (
                "register_body_identity", "resolve_body_identity",
                "list_body_identities", "semantic_extrude", "semantic_cut"):
            self.assertTrue(callable(getattr(SolidWorksAutomation, name, None)))

    def test_public_semantic_cut_uses_resilient_resolver(self):
        self.assertEqual(
            SolidWorksAutomation.semantic_cut.__module__,
            "solidworks_mcp.automation.body_identity_resilient")
        self.assertEqual(
            SolidWorksAutomation._find_body_by_identity.__module__,
            "solidworks_mcp.automation.body_identity_resilient")


if __name__ == "__main__":
    unittest.main()

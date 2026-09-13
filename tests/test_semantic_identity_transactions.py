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

    def test_capabilities_report_semantic_tool_registration(self):
        automation = SolidWorksAutomation()
        result = automation.get_capabilities()
        self.assertTrue(result["success"], result)
        capability = result["data"]["semantic_body_identity"]
        self.assertTrue(capability["available"])
        self.assertTrue(all(capability["tool_registry_exposed"].values()))
        self.assertEqual(capability["logical_id_prefix"], "body:")
        self.assertEqual(capability["canonical_body_prefix"], "B_")
        self.assertTrue(
            capability["client_schema_refresh_required_after_toolset_change"])


if __name__ == "__main__":
    unittest.main()

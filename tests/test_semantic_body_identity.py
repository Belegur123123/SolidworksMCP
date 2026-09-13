import asyncio
import unittest
from types import SimpleNamespace

from solidworks_mcp.automation.body_identity import (
    BodyIdentityOperations, register_identity_tools)
from solidworks_mcp.automation.runtime import structured_error
from solidworks_mcp.constants import SwErrors
from solidworks_mcp import tool_registry
from solidworks_mcp.server import list_tools


class _Body:
    def __init__(self, name, box=None, face_count=6):
        self.Name = name
        self._box = box or [0.0, 0.0, 0.0, 0.1, 0.02, 0.08]
        self._face_count = face_count

    def GetBodyBox(self):
        return list(self._box)

    def GetFaceCount(self):
        return self._face_count


class _Feature:
    def __init__(self, name):
        self.Name = name


class _Doc:
    def __init__(self, bodies=None, features=None):
        self.bodies = list(bodies or [])
        self.features = list(features or [])


class _Harness(BodyIdentityOperations):
    def __init__(self, doc):
        self.doc = doc
        self._runtime = SimpleNamespace(body_identities={})
        self.extrude_calls = []
        self.cut_calls = []

    def get_active_doc(self):
        return self.doc, None

    def _get_doc_path(self, doc):
        return r"C:\Temp\IdentityTest.SLDPRT"

    def _get_doc_title(self, doc):
        return "IdentityTest.SLDPRT"

    def _get_solid_bodies(self, doc, include_hidden=True):
        return list(doc.bodies)

    def _find_body(self, doc, name):
        return next((body for body in doc.bodies if body.Name == name), None)

    def _body_names(self, doc):
        return [body.Name for body in doc.bodies]

    def _find_feature(self, doc, name):
        return next((feature for feature in doc.features
                     if feature.Name == name), None)

    def _feature_names(self, doc):
        return [feature.Name for feature in doc.features]

    def _delete_feature_object(self, doc, feature, name,
                               delete_absorbed=False):
        if feature in doc.features:
            doc.features.remove(feature)
            return True
        return False

    def _result(self, success, message, error_code=SwErrors.swSuccess, data=None):
        return {
            "success": bool(success),
            "message": message,
            "error_code": int(error_code),
            "error_name": error_code.name,
            "data": dict(data or {}),
        }

    def _error(self, code, message, **kwargs):
        data = dict(kwargs.pop("data", {}) or {})
        data["error"] = structured_error(code, message, **kwargs)
        return self._result(False, message, SwErrors.swUnknownError, data)

    def advanced_extrude(self, **kwargs):
        self.extrude_calls.append(dict(kwargs))
        feature_name = kwargs.get("feature_name") or "Boss-Extrude1"
        feature = _Feature(feature_name)
        # Mimic the relevant SW2026 behavior: the newly created body may carry
        # the same display name as the owning feature until explicitly renamed.
        body = _Body(feature_name)
        self.doc.features.append(feature)
        self.doc.bodies.append(body)
        return self._result(True, "extrude", data={
            "feature_name": feature_name,
            "new_bodies": [feature_name],
            "body_names_after": [item.Name for item in self.doc.bodies],
        })

    def advanced_cut(self, **kwargs):
        self.cut_calls.append(dict(kwargs))
        feature_name = kwargs.get("feature_name") or "Cut-Extrude1"
        self.doc.features.append(_Feature(feature_name))
        return self._result(True, "cut", data={
            "feature_name": feature_name,
            "body_names_after": [item.Name for item in self.doc.bodies],
            "new_bodies": [],
            "merged_bodies": [],
        })


class SemanticBodyIdentityTests(unittest.TestCase):
    def test_register_migrates_legacy_body_without_renaming_feature(self):
        body = _Body("BaseExtrude20")
        source = _Feature("BaseExtrude20")
        automation = _Harness(_Doc([body], [source]))

        result = automation.register_body_identity(
            "body:insert_main", body_name="BaseExtrude20",
            role="main_insert_body")

        self.assertTrue(result["success"], result)
        self.assertEqual(body.Name, "B_insert_main")
        self.assertEqual(source.Name, "BaseExtrude20")
        identity = result["data"]["identity"]
        self.assertEqual(identity["logical_id"], "body:insert_main")
        self.assertEqual(identity["canonical_name"], "B_insert_main")
        self.assertEqual(identity["role"], "main_insert_body")

    def test_identity_rehydrates_from_canonical_name_after_registry_loss(self):
        body = _Body("B_insert_main")
        automation = _Harness(_Doc([body], []))
        automation._runtime.body_identities.clear()

        result = automation.resolve_body_identity("body:insert_main")

        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["body_name"], "B_insert_main")
        self.assertEqual(
            result["data"]["identity"]["resolved_by"], "canonical_name")

    def test_list_infers_durable_identity_from_persisted_body_name(self):
        automation = _Harness(_Doc([
            _Body("B_insert_main"), _Body("LegacyBody")], []))

        result = automation.list_body_identities()

        self.assertTrue(result["success"], result)
        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(
            result["data"]["identities"][0]["logical_id"],
            "body:insert_main")

    def test_semantic_extrude_separates_feature_and_body_namespaces(self):
        automation = _Harness(_Doc())

        result = automation.semantic_extrude(
            body_id="body:insert_main",
            sketch_name="S_base_profile",
            feature_name="F_base_extrude",
            depth=20,
            unit="mm")

        self.assertTrue(result["success"], result)
        self.assertEqual(automation.doc.features[0].Name, "F_base_extrude")
        self.assertEqual(automation.doc.bodies[0].Name, "B_insert_main")
        self.assertEqual(
            result["data"]["body_identity"]["logical_id"],
            "body:insert_main")
        self.assertEqual(
            result["data"]["body_identity"]["current_name"],
            "B_insert_main")

    def test_semantic_cut_resolves_logical_scope_to_canonical_body(self):
        body = _Body("B_insert_main")
        automation = _Harness(_Doc([body], [_Feature("F_base_extrude")]))

        result = automation.semantic_cut(
            scope_body_ids=["body:insert_main"],
            sketch_name="S_card_pocket",
            feature_name="F_card_pocket",
            depth=15,
            unit="mm")

        self.assertTrue(result["success"], result)
        self.assertEqual(
            automation.cut_calls[0]["scope_bodies"], ["B_insert_main"])
        self.assertEqual(body.Name, "B_insert_main")
        self.assertTrue(result["data"]["semantic_identity_verified"])
        self.assertEqual(
            result["data"]["scope_body_ids"], ["body:insert_main"])

    def test_semantic_extrude_rejects_feature_body_name_collision(self):
        automation = _Harness(_Doc())

        result = automation.semantic_extrude(
            body_id="body:insert_main",
            feature_name="B_insert_main")

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["error"]["code"], "INVALID_PLAN")
        self.assertEqual(automation.extrude_calls, [])

    def test_identity_tools_are_registered_with_correct_mutability(self):
        register_identity_tools()
        names = {tool.name for tool in tool_registry.NEW_TOOLS}
        for name in ("register_body_identity", "resolve_body_identity",
                     "list_body_identities", "semantic_extrude",
                     "semantic_cut"):
            self.assertIn(name, names)
            self.assertIn(name, tool_registry.NEW_TOOL_NAMES)

        self.assertIn("register_body_identity", tool_registry.MUTATING_TOOLS)
        self.assertIn("semantic_extrude", tool_registry.MUTATING_TOOLS)
        self.assertIn("semantic_cut", tool_registry.MUTATING_TOOLS)
        self.assertNotIn("resolve_body_identity", tool_registry.MUTATING_TOOLS)
        self.assertNotIn("list_body_identities", tool_registry.MUTATING_TOOLS)
        self.assertIn("semantic_extrude", tool_registry.FIRST_GEOMETRY_TOOLS)
        self.assertIn("semantic_cut", tool_registry.FIRST_GEOMETRY_TOOLS)

    def test_server_exposes_semantic_identity_tools(self):
        tools = asyncio.run(list_tools())
        names = {tool.name for tool in tools}
        self.assertTrue({
            "register_body_identity", "resolve_body_identity",
            "list_body_identities", "semantic_extrude", "semantic_cut"
        }.issubset(names))

        semantic_cut = next(tool for tool in tools
                            if tool.name == "semantic_cut")
        self.assertIn("scope_body_ids", semantic_cut.inputSchema["properties"])
        self.assertIn("budget", semantic_cut.inputSchema["properties"])
        resolve = next(tool for tool in tools
                       if tool.name == "resolve_body_identity")
        self.assertNotIn("budget", resolve.inputSchema["properties"])


if __name__ == "__main__":
    unittest.main()

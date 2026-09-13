import unittest
from unittest.mock import patch

import solidworks_mcp.automation.advanced_features_sw2026 as sw2026
from solidworks_mcp.automation.advanced_features_sw2026 import (
    AdvancedFeatureOperations,
)


class _NamedObject:
    def __init__(self, name):
        self.Name = name


class _Doc:
    def __init__(self, features=None, bodies=None):
        self.features = list(features or [])
        self.bodies = list(bodies or [])


class _Harness(AdvancedFeatureOperations):
    def __init__(self, doc):
        self.doc = doc

    def get_active_doc(self):
        return self.doc, None

    def _find_feature(self, doc, name):
        return next((f for f in doc.features if f.Name == name), None)

    def _find_body(self, doc, name):
        return next((b for b in doc.bodies if b.Name == name), None)

    def _feature_names(self, doc):
        return [f.Name for f in doc.features]

    def _body_names(self, doc):
        return [b.Name for b in doc.bodies]

    def _delete_feature_object(self, doc, feat, name,
                               delete_absorbed=False):
        if feat in doc.features:
            doc.features.remove(feat)
            return True
        return False

    def _result(self, success, message, error_code, data=None):
        return {
            "success": bool(success),
            "message": message,
            "error_code": int(error_code),
            "error_name": str(error_code),
            "data": dict(data or {}),
        }


def _base_cut_result():
    return {
        "success": True,
        "message": "Cut 'PocketCut15' created",
        "error_code": 0,
        "error_name": "swSuccess",
        "data": {
            "feature_name": "PocketCut15",
            "bodies_before": 1,
            "bodies_after": 1,
            "body_names_before": ["BaseExtrude20"],
            "body_names_after": ["BaseExtrude20"],
            "merged_bodies": [],
            "new_bodies": [],
            "scope_name_restorations": [
                {"from": "PocketCut15", "to": "BaseExtrude20"}
            ],
            "scope_feature_renames": [{
                "from": "BaseExtrude20",
                "to": "BaseExtrude20_SourceFeature",
                "reason": "body_name_namespace_collision",
                "rename_warning": None,
            }],
        },
    }


class SW2026CutNameStabilityTests(unittest.TestCase):
    def test_scoped_cut_restores_source_feature_and_aliases_body(self):
        source = _NamedObject("BaseExtrude20_SourceFeature")
        cut = _NamedObject("PocketCut15")
        body = _NamedObject("BaseExtrude20")
        doc = _Doc(features=[source, cut], bodies=[body])
        automation = _Harness(doc)

        with patch.object(
                sw2026._BaseAdvancedFeatures,
                "advanced_cut",
                return_value=_base_cut_result()):
            result = automation.advanced_cut(
                sketch_name="Skizze1",
                scope_bodies=["BaseExtrude20"],
                feature_name="PocketCut15")

        self.assertTrue(result["success"], result)
        self.assertEqual(source.Name, "BaseExtrude20")
        self.assertEqual(cut.Name, "PocketCut15")
        self.assertEqual(body.Name, "BaseExtrude20_Body")
        self.assertEqual(
            result["data"]["body_names_after"],
            ["BaseExtrude20_Body"])
        self.assertEqual(result["data"]["scope_feature_renames"], [])
        self.assertTrue(result["data"]["source_feature_names_preserved"])
        self.assertEqual(result["data"]["scope_body_name_changes"], [{
            "from": "BaseExtrude20",
            "to": "BaseExtrude20_Body",
            "reason": "preserve_existing_feature_name",
        }])
        self.assertEqual(result["data"]["merged_bodies"], [])
        self.assertEqual(result["data"]["new_bodies"], [])

    def test_body_alias_is_suffixed_when_default_alias_is_taken(self):
        source = _NamedObject("BaseExtrude20_SourceFeature")
        cut = _NamedObject("PocketCut15")
        occupied = _NamedObject("BaseExtrude20_Body")
        body = _NamedObject("BaseExtrude20")
        doc = _Doc(features=[source, cut, occupied], bodies=[body])
        automation = _Harness(doc)

        with patch.object(
                sw2026._BaseAdvancedFeatures,
                "advanced_cut",
                return_value=_base_cut_result()):
            result = automation.advanced_cut(
                sketch_name="Skizze1",
                scope_bodies=["BaseExtrude20"],
                feature_name="PocketCut15")

        self.assertTrue(result["success"], result)
        self.assertEqual(source.Name, "BaseExtrude20")
        self.assertEqual(body.Name, "BaseExtrude20_Body_2")
        self.assertEqual(
            result["data"]["scope_body_name_changes"][0]["to"],
            "BaseExtrude20_Body_2")

    def test_cut_without_collision_is_unchanged(self):
        source = _NamedObject("BaseExtrude20")
        cut = _NamedObject("PocketCut15")
        body = _NamedObject("InsertBody")
        doc = _Doc(features=[source, cut], bodies=[body])
        automation = _Harness(doc)
        base_result = _base_cut_result()
        base_result["data"]["scope_feature_renames"] = []
        base_result["data"]["scope_name_restorations"] = []
        base_result["data"]["body_names_after"] = ["InsertBody"]

        with patch.object(
                sw2026._BaseAdvancedFeatures,
                "advanced_cut",
                return_value=base_result):
            result = automation.advanced_cut(
                sketch_name="Skizze1",
                scope_bodies=["InsertBody"],
                feature_name="PocketCut15")

        self.assertTrue(result["success"], result)
        self.assertEqual(source.Name, "BaseExtrude20")
        self.assertEqual(body.Name, "InsertBody")
        self.assertEqual(result["data"]["scope_body_name_changes"], [])
        self.assertTrue(result["data"]["source_feature_names_preserved"])

    def test_missing_feature_has_specific_structured_error(self):
        doc = _Doc()
        automation = _Harness(doc)
        missing = {
            "success": False,
            "message": "Feature 'MissingFeature' not found",
            "error_code": 104,
            "error_name": "swSelectionError",
            "data": {"existing_features": ["BaseExtrude20"]},
        }

        with patch.object(
                sw2026._BaseAdvancedFeatures,
                "get_feature_status",
                return_value=missing):
            result = automation.get_feature_status("MissingFeature")

        self.assertFalse(result["success"])
        error = result["data"]["error"]
        self.assertEqual(error["code"], "FEATURE_NOT_FOUND")
        self.assertEqual(error["stage"], "lookup")
        self.assertTrue(error["recoverable"])
        self.assertEqual(
            error["details"]["existing_features"],
            ["BaseExtrude20"])


if __name__ == "__main__":
    unittest.main()

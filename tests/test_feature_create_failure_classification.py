import unittest

from solidworks_mcp.automation.runtime import enrich_legacy_error


class FeatureCreateFailureClassificationTests(unittest.TestCase):
    def test_rejected_cut_is_not_misclassified_as_com_member_mismatch(self):
        result = enrich_legacy_error({
            "success": False,
            "message": "Cut failed on sketch 'Skizze1'",
            "error_code": 103,
            "error_name": "swFeatureError",
            "data": {
                "api_error": None,
                "typed_feature_manager": True,
                "flags": {
                    "direction_flip": True,
                    "offset_reverse": False,
                    "flip_start_offset": False,
                },
            },
        })

        error = result["data"]["error"]
        self.assertEqual(error["code"], "FEATURE_CREATE_FAILED")
        self.assertEqual(error["stage"], "create_feature")
        self.assertIsNone(error["com_hresult"])
        self.assertIn("direction", " ".join(error["recommended_actions"]).lower())

    def test_real_unknown_legacy_failure_still_uses_com_member_mismatch_fallback(self):
        result = enrich_legacy_error({
            "success": False,
            "message": "Unknown COM automation failure",
            "error_code": 103,
            "error_name": "swFeatureError",
        })
        self.assertEqual(
            result["data"]["error"]["code"], "COM_MEMBER_MISMATCH")


if __name__ == "__main__":
    unittest.main()

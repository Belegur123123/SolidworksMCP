import unittest
from types import SimpleNamespace

from solidworks_mcp.automation.body_identity_resilient import BodyIdentityOperations
from solidworks_mcp.automation.runtime import structured_error
from solidworks_mcp.constants import SwErrors


class _Configuration:
    def __init__(self, name):
        self.Name = name


class _ConfigurationManager:
    def __init__(self, name):
        self.ActiveConfiguration = _Configuration(name)


class _Body:
    def __init__(self, name, box=None, faces=6):
        self.Name = name
        self._box = box or [0.0, 0.0, 0.0, 0.1, 0.02, 0.08]
        self._faces = faces

    def GetBodyBox(self):
        return list(self._box)

    def GetFaceCount(self):
        return self._faces


class _Doc:
    def __init__(self, bodies=None, configuration="Default"):
        self.bodies = list(bodies or [])
        self.features = []
        self.ConfigurationManager = _ConfigurationManager(configuration)


class _Harness(BodyIdentityOperations):
    def __init__(self, doc):
        self.doc = doc
        self._runtime = SimpleNamespace(body_identities={})
        self.cut_calls = []
        self.direction_calls = []

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
                     if getattr(feature, "Name", None) == name), None)

    def _feature_names(self, doc):
        return [feature.Name for feature in doc.features]

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

    def advanced_cut(self, **kwargs):
        self.cut_calls.append(dict(kwargs))
        return self._result(True, "cut", data={"feature_name": "F_cut"})

    def resolve_cut_direction(self, **kwargs):
        self.direction_calls.append(dict(kwargs))
        return self._result(True, "direction", data={
            "direction_flip": False,
            "material_side": "negative_normal",
            "method": "test_resolver",
        })


class SemanticIdentityResilienceTests(unittest.TestCase):
    def test_auto_bbox_failure_does_not_recommend_trial_flags(self):
        automation = _Harness(_Doc([_Body('B_insert_main')]))
        automation.advanced_cut = lambda **kw: automation._result(
            False, 'Cut landed OUTSIDE the expected zone. Feature rolled back. '
            'Try flipping flip_start_offset/direction_flip or auto_flags=true.',
            SwErrors.swFeatureError, {'feature_deleted': True})
        result = automation.semantic_cut(['body:insert_main'], direction_mode='auto_material_side')
        self.assertFalse(result['success'])
        self.assertNotIn('auto_flags=true', result['message'])
        self.assertIn('verify expected_bbox', result['message'])
        self.assertTrue(result['data']['feature_deleted'])

    def test_post_cut_identity_failure_rolls_back_and_rehydrates_identity(self):
        class RollbackHarness(_Harness):
            def advanced_cut(self, **kwargs):
                result = super().advanced_cut(**kwargs)
                self.original_body = self.doc.bodies[0]
                self.doc.bodies = []
                self.doc.features.append(SimpleNamespace(Name='F_cut'))
                return result

            def _delete_feature_object(self, doc, feature, name, delete_absorbed):
                self.rollback_delete_absorbed = delete_absorbed
                doc.features.remove(feature)
                doc.bodies = [self.original_body]
                return True

        automation = RollbackHarness(_Doc([_Body('B_insert_main')]))
        result = automation.semantic_cut(['body:insert_main'], direction_mode='auto_material_side')
        self.assertFalse(result['success'])
        self.assertEqual(result['data']['error']['code'], 'INVARIANT_FAILED')
        self.assertTrue(result['data']['semantic_identity_rollback']['feature_deleted'])
        self.assertFalse(automation.rollback_delete_absorbed)
        self.assertEqual(automation.doc.features, [])
        body, record, error = automation._find_body_by_identity(automation.doc, 'body:insert_main')
        self.assertIsNone(error)
        self.assertEqual(record['current_name'], 'B_insert_main')
        self.assertEqual(len(automation.cut_calls), 1)

    def test_failed_feature_deletion_is_not_reported_as_restored(self):
        class FailedRollbackHarness(_Harness):
            def advanced_cut(self, **kwargs):
                result = super().advanced_cut(**kwargs)
                self.doc.bodies = []
                self.doc.features.append(SimpleNamespace(Name='F_cut'))
                return result

            def _delete_feature_object(self, *args, **kwargs):
                return False

        automation = FailedRollbackHarness(_Doc([_Body('B_insert_main')]))
        result = automation.semantic_cut(['body:insert_main'])
        self.assertFalse(result['success'])
        self.assertFalse(result['data']['semantic_identity_rollback']['feature_deleted'])
        self.assertFalse(result['data']['error']['document_restored'])

    def test_explicit_direction_is_forwarded_without_resolver(self):
        for flag in (False, True):
            with self.subTest(flag=flag):
                automation = _Harness(_Doc([_Body('B_insert_main')]))
                result = automation.semantic_cut(['body:insert_main'], direction_flip=flag,
                                                 direction_mode='explicit')
                self.assertTrue(result['success'], result)
                self.assertEqual(automation.direction_calls, [])
                self.assertEqual(len(automation.cut_calls), 1)
                self.assertIs(automation.cut_calls[0]['direction_flip'], flag)

    def test_failed_auto_preflight_never_calls_cut(self):
        automation = _Harness(_Doc([_Body('B_insert_main')]))
        automation.resolve_cut_direction = lambda **kw: automation._error(
            'INVALID_PLAN', 'ambiguous', stage='validate_geometry')
        result = automation.semantic_cut(['body:insert_main'], direction_mode='auto_material_side')
        self.assertFalse(result['success'])
        self.assertEqual(automation.cut_calls, [])
        self.assertEqual(automation._body_names(automation.doc), ['B_insert_main'])

    def test_malformed_successful_preflight_never_calls_cut(self):
        for value in (None, 0, 'false'):
            with self.subTest(value=value):
                automation = _Harness(_Doc([_Body('B_insert_main')]))
                automation.resolve_cut_direction = lambda **kw: automation._result(
                    True, 'malformed', data={'direction_flip': value})
                result = automation.semantic_cut(['body:insert_main'], direction_mode='auto_material_side')
                self.assertFalse(result['success'])
                self.assertEqual(result['data']['error']['code'], 'INVARIANT_FAILED')
                self.assertEqual(automation.cut_calls, [])

    def test_auto_rejects_retry_flags_and_shifted_start_before_geometry(self):
        for args in ({'auto_flags': True}, {'start_condition': 'offset'},
                     {'start_offset': 2}, {'start_face_ray': {}}):
            with self.subTest(args=args):
                automation = _Harness(_Doc([_Body('B_insert_main')]))
                result = automation.semantic_cut(['body:insert_main'],
                                                 direction_mode='auto_material_side', **args)
                self.assertFalse(result['success'])
                self.assertEqual(automation.cut_calls, [])
                self.assertEqual(automation.direction_calls, [])

    def test_canonical_body_wins_over_stale_session_name(self):
        canonical = _Body("B_insert_main")
        stale_name_reused = _Body(
            "OldBody", box=[0.0, 0.0, 0.0, 0.2, 0.02, 0.08])
        automation = _Harness(_Doc([canonical, stale_name_reused]))
        key = automation._identity_document_key(automation.doc)
        automation._runtime.body_identities[(key, "body:insert_main")] = {
            "logical_id": "body:insert_main",
            "current_name": "OldBody",
            "canonical_name": "B_insert_main",
            "role": "main_insert_body",
            "signature": {"bbox_m": [0.0, 0.0, 0.0, 0.1, 0.02, 0.08],
                          "face_count": 6},
        }

        body, record, error = automation._find_body_by_identity(
            automation.doc, "body:insert_main")

        self.assertIsNone(error)
        self.assertIs(body, canonical)
        self.assertEqual(record["resolved_by"], "canonical_name")
        self.assertEqual(record["current_name"], "B_insert_main")

    def test_stale_session_name_must_match_recorded_signature(self):
        replacement = _Body(
            "OldBody", box=[0.0, 0.0, 0.0, 0.2, 0.02, 0.08])
        actual = _Body(
            "RenamedActual", box=[0.0, 0.0, 0.0, 0.1, 0.02, 0.08])
        automation = _Harness(_Doc([replacement, actual]))
        key = automation._identity_document_key(automation.doc)
        automation._runtime.body_identities[(key, "body:insert_main")] = {
            "logical_id": "body:insert_main",
            "current_name": "OldBody",
            "canonical_name": "B_insert_main",
            "role": None,
            "signature": {"bbox_m": [0.0, 0.0, 0.0, 0.1, 0.02, 0.08],
                          "face_count": 6},
        }

        body, record, error = automation._find_body_by_identity(
            automation.doc, "body:insert_main")

        self.assertIsNone(error)
        self.assertIs(body, actual)
        self.assertEqual(record["resolved_by"], "geometry_signature")
        self.assertEqual(record["current_name"], "RenamedActual")

    def test_registry_isolated_by_active_configuration(self):
        doc = _Doc([_Body("B_insert_main")], configuration="Default")
        automation = _Harness(doc)
        default_key = automation._identity_document_key(doc)
        doc.ConfigurationManager.ActiveConfiguration = _Configuration("Print")
        print_key = automation._identity_document_key(doc)

        self.assertNotEqual(default_key, print_key)
        self.assertIn("::config:default", default_key)
        self.assertIn("::config:print", print_key)

    def test_semantic_cut_rejects_noncanonical_scope_before_advanced_cut(self):
        legacy = _Body("LegacyBody")
        automation = _Harness(_Doc([legacy]))
        automation._record_body_identity(
            automation.doc, "body:insert_main", legacy,
            source="explicit_noncanonical")

        result = automation.semantic_cut(
            scope_body_ids=["body:insert_main"],
            sketch_name="S_pocket",
            feature_name="F_pocket",
            depth=15,
            unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["error"]["code"], "REFERENCE_MISMATCH")
        self.assertEqual(automation.cut_calls, [])
        self.assertEqual(automation.direction_calls, [])

    def test_semantic_cut_auto_direction_overrides_supplied_flag_before_cut(self):
        automation = _Harness(_Doc([_Body("B_insert_main")]))

        result = automation.semantic_cut(
            scope_body_ids=["body:insert_main"],
            sketch_name="S_pocket",
            feature_name="F_pocket",
            depth=15,
            direction_flip=True,
            direction_mode="auto_material_side",
            direction_tolerance=0.01,
            unit="mm")

        self.assertTrue(result["success"], result)
        self.assertEqual(len(automation.direction_calls), 1)
        self.assertEqual(len(automation.cut_calls), 1)
        self.assertFalse(automation.cut_calls[0]["direction_flip"])
        data = result["data"]
        self.assertEqual(data["direction_mode"], "auto_material_side")
        self.assertTrue(data["requested_direction_flip"])
        self.assertFalse(data["effective_direction_flip"])
        self.assertFalse(data["cut_direction_preflight"]["direction_flip"])
        self.assertEqual(
            data["semantic_scope_preflight"][0]["canonical_name"],
            "B_insert_main")


if __name__ == "__main__":
    unittest.main()

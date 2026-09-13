import unittest
from types import SimpleNamespace

from solidworks_mcp.automation.cut_direction import (
    CutDirectionOperations, register_cut_direction_tools)
from solidworks_mcp.automation.body_identity import register_identity_tools
from solidworks_mcp.automation.runtime import structured_error
from solidworks_mcp.automation.view import ViewOperations
from solidworks_mcp.constants import SwErrors
from solidworks_mcp import tool_registry


class _Units:
    default_unit = SimpleNamespace(value="mm")

    @staticmethod
    def to_meters(value, unit=None):
        unit = unit or "mm"
        if unit == "m":
            return float(value)
        if unit == "inch":
            return float(value) * 0.0254
        return float(value) * 0.001

    @staticmethod
    def from_meters(value, unit=None):
        unit = unit or "mm"
        if unit == "m":
            return float(value)
        if unit == "inch":
            return float(value) / 0.0254
        return float(value) * 1000.0


class _Transform:
    def __init__(self, data, inverse=None):
        self.ArrayData = list(data)
        self.Inverse = inverse


class _Sketch:
    def __init__(self, origin_y=0.02):
        # Same basis as the live D2 sketch: +X, -Z, +Y(normal).
        model_to_sketch = [
            1.0, 0.0, 0.0,
            0.0, 0.0, 1.0,
            0.0, -1.0, 0.0,
            0.0, 0.0, 0.0,
            1.0, 0.0, 0.0, 0.0,
        ]
        sketch_to_model = [
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
            0.0, 0.0, 1.0,
            0.0, float(origin_y), 0.0,
            1.0, 0.0, 0.0, 0.0,
        ]
        inverse = _Transform(sketch_to_model)
        self.ModelToSketchTransform = _Transform(model_to_sketch, inverse)


class _Feature:
    def __init__(self, name, sketch=None):
        self.Name = name
        self._sketch = sketch

    def GetSpecificFeature2(self):
        return self._sketch


class _Body:
    def __init__(self, name, box):
        self.Name = name
        self._box = list(box)

    def GetBodyBox(self):
        return list(self._box)


class _Doc:
    def __init__(self, feature, bodies):
        self.features = [feature]
        self.bodies = list(bodies)


class _Harness(CutDirectionOperations, ViewOperations):
    def __init__(self, body_box, sketch_origin_y=0.02):
        self._units = _Units()
        self.body = _Body("B_insert_main", body_box)
        self.feature = _Feature("S_pocket", _Sketch(sketch_origin_y))
        self.doc = _Doc(self.feature, [self.body])

    def get_active_doc(self):
        return self.doc, None

    def _find_feature(self, doc, name):
        return next((feature for feature in doc.features
                     if feature.Name == name), None)

    def _feature_names(self, doc):
        return [feature.Name for feature in doc.features]

    def _find_body_by_identity(self, doc, body_id):
        if body_id != "body:insert_main":
            return None, None, self._error(
                "REFERENCE_MISMATCH", "missing body",
                stage="validate_reference", recoverable=True)
        record = {
            "logical_id": body_id,
            "canonical_name": "B_insert_main",
            "current_name": "B_insert_main",
        }
        return self.body, record, None

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


class CutDirectionTests(unittest.TestCase):
    def test_negative_normal_material_resolves_false_for_d2_geometry(self):
        automation = _Harness(
            [-0.07, 0.0, -0.04, 0.06, 0.02, 0.04])

        result = automation.resolve_cut_direction(
            ["body:insert_main"], "S_pocket",
            direction_tolerance=0.01, unit="mm")

        self.assertTrue(result["success"], result)
        data = result["data"]
        self.assertFalse(data["direction_flip"])
        self.assertEqual(data["material_side"], "negative_normal")
        self.assertEqual(data["sketch_normal"], [0.0, 1.0, 0.0])
        self.assertAlmostEqual(data["sketch_origin"][1], 20.0, places=9)
        self.assertAlmostEqual(
            data["bodies"][0]["min_signed_distance"], -20.0, places=9)
        self.assertAlmostEqual(
            data["bodies"][0]["max_signed_distance"], 0.0, places=9)

    def test_positive_normal_material_resolves_true(self):
        automation = _Harness(
            [-0.07, 0.02, -0.04, 0.06, 0.04, 0.04])

        result = automation.resolve_cut_direction(
            ["body:insert_main"], "S_pocket", unit="mm")

        self.assertTrue(result["success"], result)
        self.assertTrue(result["data"]["direction_flip"])
        self.assertEqual(result["data"]["material_side"], "positive_normal")

    def test_spanning_body_fails_closed(self):
        automation = _Harness(
            [-0.07, 0.01, -0.04, 0.06, 0.03, 0.04])

        result = automation.resolve_cut_direction(
            ["body:insert_main"], "S_pocket", unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["error"]["code"], "INVALID_PLAN")
        self.assertEqual(
            result["data"]["error"]["stage"], "validate_geometry")

    def test_tool_registry_exposes_resolver_and_auto_mode_schema(self):
        register_identity_tools()
        register_cut_direction_tools()
        names = {tool.name for tool in tool_registry.NEW_TOOLS}
        self.assertIn("resolve_cut_direction", names)
        self.assertIn("resolve_cut_direction", tool_registry.NEW_TOOL_NAMES)
        self.assertNotIn("resolve_cut_direction", tool_registry.MUTATING_TOOLS)

        semantic_cut = next(
            tool for tool in tool_registry.NEW_TOOLS
            if tool.name == "semantic_cut")
        props = semantic_cut.inputSchema["properties"]
        self.assertEqual(
            props["direction_mode"]["enum"],
            ["explicit", "auto_material_side"])
        self.assertIn("direction_tolerance", props)

    def test_invalid_tolerance_fails_closed(self):
        for value in (-0.01, float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value):
                automation = _Harness([-0.07, 0, -0.04, 0.06, 0.02, 0.04])
                result = automation.resolve_cut_direction(
                    ['body:insert_main'], 'S_pocket', direction_tolerance=value)
                self.assertFalse(result['success'])
                self.assertEqual(result['data']['error']['code'], 'INVALID_PLAN')

    def test_invalid_bbox_fails_closed(self):
        for box in ([float('nan'), 0, 0, 0.06, 0.02, 0.04],
                    [0, 0, 0, float('inf'), 0.02, 0.04],
                    [0.07, 0, 0, 0.06, 0.02, 0.04],
                    [0, 0, 0, 'bad', 0.02, 0.04], [0, 0, 0]):
            with self.subTest(box=box):
                automation = _Harness(box)
                result = automation.resolve_cut_direction(['body:insert_main'], 'S_pocket')
                self.assertFalse(result['success'])
                self.assertEqual(result['data']['error']['stage'], 'validate_geometry')

    def test_nonfinite_transform_fails_closed(self):
        automation = _Harness([-0.07, 0, -0.04, 0.06, 0.02, 0.04])
        automation.feature._sketch.ModelToSketchTransform.ArrayData[0] = float('nan')
        result = automation.resolve_cut_direction(['body:insert_main'], 'S_pocket')
        self.assertFalse(result['success'])
        self.assertEqual(result['data']['error']['code'], 'REFERENCE_MISMATCH')

    def test_missing_references_fail_closed(self):
        for ids, name in [(['body:missing'], 'S_pocket'), (['body:insert_main'], 'missing')]:
            with self.subTest(ids=ids, name=name):
                automation = _Harness([-0.07, 0, -0.04, 0.06, 0.02, 0.04])
                result = automation.resolve_cut_direction(ids, name)
                self.assertFalse(result['success'])
                self.assertEqual(result['data']['error']['code'], 'REFERENCE_MISMATCH')

    def test_opposite_scope_sides_fail_closed(self):
        automation = _Harness([-0.07, 0, -0.04, 0.06, 0.02, 0.04])
        second = _Body('B_upper', [-0.07, 0.02, -0.04, 0.06, 0.04, 0.04])
        original = automation._find_body_by_identity
        automation._find_body_by_identity = lambda doc, body_id: (
            (second, {'current_name': 'B_upper'}, None) if body_id == 'body:upper'
            else original(doc, body_id))
        result = automation.resolve_cut_direction(['body:insert_main', 'body:upper'], 'S_pocket')
        self.assertFalse(result['success'])
        self.assertEqual(result['data']['error']['code'], 'INVALID_PLAN')
        self.assertEqual(len(result['data']['error']['details']['body_sides']), 2)

    def test_unit_conversion_preserves_direction(self):
        for unit, tolerance, expected in [('mm', 0.01, -20), ('m', 0.00001, -0.02),
                                           ('inch', 0.01 / 25.4, -20 / 25.4)]:
            with self.subTest(unit=unit):
                automation = _Harness([-0.07, 0, -0.04, 0.06, 0.02, 0.04])
                result = automation.resolve_cut_direction(['body:insert_main'], 'S_pocket', tolerance, unit)
                self.assertTrue(result['success'], result)
                self.assertFalse(result['data']['direction_flip'])
                self.assertAlmostEqual(result['data']['bodies'][0]['min_signed_distance'], expected)

    def test_registration_is_idempotent_and_documents_cut_rule(self):
        register_identity_tools()
        register_cut_direction_tools()
        register_cut_direction_tools()
        for name in ('semantic_cut', 'resolve_cut_direction'):
            self.assertEqual(sum(tool.name == name for tool in tool_registry.NEW_TOOLS), 1)
        tool = next(tool for tool in tool_registry.NEW_TOOLS if tool.name == 'semantic_cut')
        description = tool.inputSchema['properties']['direction_flip']['description']
        self.assertIn('false = opposite sketch normal', description)
        self.assertIn('true = along sketch normal', description)


if __name__ == "__main__":
    unittest.main()

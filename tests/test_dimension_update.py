"""Regression coverage for safe edits of existing driving dimensions."""

import unittest
from types import SimpleNamespace

from solidworks_mcp.automation.dimension_update import DimensionUpdateOperations


class FakeUnits:
    default_unit = SimpleNamespace(value="mm")

    @staticmethod
    def to_meters(value, unit):
        if unit == "mm":
            return float(value) / 1000.0
        if unit == "m":
            return float(value)
        raise ValueError(unit)

    @staticmethod
    def from_meters(value, unit):
        if unit == "mm":
            return float(value) * 1000.0
        if unit == "m":
            return float(value)
        raise ValueError(unit)


class FakeRuntime:
    def __init__(self):
        self.rollbacks = 0

    def increment(self, key, amount=1):
        if key == "rollbacks":
            self.rollbacks += amount


class FakeDimension:
    def __init__(self, value_m, driven_state=2):
        self.SystemValue = float(value_m)
        self.DrivenState = int(driven_state)


class FakeDocument:
    """Model SW2026 property-style dispatch for zero-arg GetFeatureCount."""

    def __init__(self, name, dimension, feature_count=19):
        self._name = name
        self._dimension = dimension
        # Deliberately an integer, not a callable.  Direct
        # doc.GetFeatureCount() would fail with "'int' object is not callable".
        self.GetFeatureCount = int(feature_count)
        self.rebuilds = 0

    def Parameter(self, name):
        return self._dimension if name == self._name else None

    def EditRebuild3(self):
        self.rebuilds += 1
        return True


class Harness(DimensionUpdateOperations):
    def __init__(self, doc):
        self.doc = doc
        self._units = FakeUnits()
        self._runtime = FakeRuntime()
        self.rebuild_metric = 0

    def get_active_doc(self):
        return self.doc, None

    def record_rebuild(self, elapsed_sec=0.0):
        self.rebuild_metric += 1

    def _result(self, success, message, error_code, data=None):
        return {"success": success, "message": message,
                "error_code": error_code, "data": data or {}}

    def _error(self, code, message, **kwargs):
        return {"success": False, "message": message,
                "data": {"error": {"code": code, **kwargs}}}


class DimensionUpdateTests(unittest.TestCase):
    def test_updates_existing_driving_dimension_without_feature_count_call(self):
        name = "D1@Sketch@Part.Part"
        dimension = FakeDimension(0.120, driven_state=2)
        doc = FakeDocument(name, dimension, feature_count=19)
        ops = Harness(doc)

        result = ops.set_dimension_value(name, 130, unit="mm")

        self.assertTrue(result["success"], result)
        self.assertAlmostEqual(dimension.SystemValue, 0.130, places=12)
        self.assertEqual(doc.rebuilds, 1)
        self.assertEqual(ops.rebuild_metric, 1)
        self.assertEqual(result["data"]["feature_count_before"], 19)
        self.assertEqual(result["data"]["feature_count_after"], 19)
        self.assertFalse(result["data"]["feature_count_changed"])
        self.assertEqual(result["data"]["before_value"], 120.0)
        self.assertEqual(result["data"]["after_value"], 130.0)

    def test_rejects_driven_dimension_before_mutation(self):
        name = "D1@Sketch@Part.Part"
        dimension = FakeDimension(0.120, driven_state=1)
        doc = FakeDocument(name, dimension)
        ops = Harness(doc)

        result = ops.set_dimension_value(name, 130, unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["error"]["code"],
                         "SKETCH_UNDERDEFINED")
        self.assertAlmostEqual(dimension.SystemValue, 0.120, places=12)
        self.assertEqual(doc.rebuilds, 0)

    def test_missing_dimension_is_non_mutating(self):
        name = "D1@Sketch@Part.Part"
        dimension = FakeDimension(0.120, driven_state=2)
        doc = FakeDocument(name, dimension)
        ops = Harness(doc)

        result = ops.set_dimension_value(
            "D9@Missing@Part.Part", 130, unit="mm")

        self.assertFalse(result["success"])
        self.assertEqual(result["data"]["error"]["code"],
                         "SKETCH_UNDERDEFINED")
        self.assertAlmostEqual(dimension.SystemValue, 0.120, places=12)
        self.assertEqual(doc.rebuilds, 0)


if __name__ == "__main__":
    unittest.main()

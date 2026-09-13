"""Regression tests for the SOLIDWORKS 2026 coincident-constraint fix."""

import unittest

from solidworks_mcp.automation import ParametricSketchOperations
from solidworks_mcp.automation.parametric import _SketchValidationError
from solidworks_mcp.automation.runtime import ERROR_DEFAULTS


class FakePoint:
    def __init__(self, x, y, z=0.0):
        self.X = x
        self.Y = y
        self.Z = z
        self.selected = []

    def Select4(self, append, selection_data):
        self.selected.append(bool(append))
        return True


class FakeSegment:
    def __init__(self, start, end):
        self.start = FakePoint(*start)
        self.end = FakePoint(*end)
        self.ConstructionGeometry = False

    def GetStartPoint2(self):
        return self.start

    def GetEndPoint2(self):
        return self.end

    def Select4(self, append, selection_data):
        return True


class FakeSketch:
    def __init__(self):
        self.relations = []

    def GetRelations(self):
        return self.relations


class FakeSketchManager:
    def __init__(self, sketch):
        self.ActiveSketch = sketch


class FakeSelectionManager:
    def CreateSelectData(self):
        return type("SelectionData", (), {"Mark": 0})()


class FakeDoc:
    def __init__(self):
        self.sketch = FakeSketch()
        self.SketchManager = FakeSketchManager(self.sketch)
        self.SelectionManager = FakeSelectionManager()
        self.constraint_handler = None
        self.constraint_calls = []

    def ClearSelection2(self, all_items):
        return True

    def SketchAddConstraints(self, code):
        self.constraint_calls.append(code)
        if self.constraint_handler is not None:
            self.constraint_handler(code)
        # The real IModelDoc2::SketchAddConstraints API is void.
        return None


class Sw2026CoincidentTests(unittest.TestCase):
    def setUp(self):
        self.ops = ParametricSketchOperations()
        self.doc = FakeDoc()
        self.left = FakeSegment((0.0, 0.0, 0.0), (0.010, 0.0, 0.0))
        self.right = FakeSegment((0.015, 0.005, 0.0), (0.030, 0.005, 0.0))
        self.records = {
            "left": {
                "object": self.left,
                "type": "line",
                "construction": False,
                "points": self.ops._entity_points(self.left),
            },
            "right": {
                "object": self.right,
                "type": "line",
                "construction": False,
                "points": self.ops._entity_points(self.right),
            },
        }

    def test_public_automation_uses_sw2026_safe_backend(self):
        self.assertEqual(
            ParametricSketchOperations.__module__,
            "solidworks_mcp.automation.parametric_sw2026")

    def test_constraint_error_is_classified_as_recoverable_solver_error(self):
        self.assertEqual(
            ERROR_DEFAULTS["SKETCH_CONSTRAINT_UNVERIFIED"],
            ("solve", True))

    def test_coincident_accepts_geometry_when_relation_count_stays_zero(self):
        stale_right_start = self.records["right"]["points"]["start"]

        def merge_points(code):
            self.assertEqual(code, "sgCOINCIDENT")
            # Reproduce the observed SW2026 behavior: endpoint topology changes,
            # the old SketchPoint wrapper is replaced, but no logical relation
            # is returned by the RelationManager.
            self.right.start = FakePoint(
                self.left.end.X, self.left.end.Y, self.left.end.Z)

        self.doc.constraint_handler = merge_points
        result = self.ops._apply_constraint(
            self.doc,
            self.records,
            {"type": "coincident",
             "entities": ["left.end", "right.start"]})

        self.assertEqual(result["before"], 0)
        self.assertEqual(result["after"], 0)
        self.assertEqual(result["verification"], "geometry")
        self.assertFalse(result["relation_count_changed"])
        self.assertEqual(result["max_error_m"], 0.0)
        self.assertIsNot(
            self.records["right"]["points"]["start"], stale_right_start)
        self.assertIs(
            self.records["right"]["points"]["start"], self.right.start)

    def test_genuine_silent_noop_is_rejected(self):
        with self.assertRaises(_SketchValidationError) as caught:
            self.ops._apply_constraint(
                self.doc,
                self.records,
                {"type": "coincident",
                 "entities": ["left.end", "right.start"]})

        self.assertEqual(caught.exception.code,
                         "SKETCH_CONSTRAINT_UNVERIFIED")
        self.assertIn("did not produce coincident geometry",
                      str(caught.exception))

    def test_next_reference_reacquires_replaced_sketch_point(self):
        stale = self.records["right"]["points"]["start"]
        replacement = FakePoint(0.020, 0.010, 0.0)
        self.right.start = replacement

        kind, resolved = self.ops._resolve_entity_ref(
            self.records, "right.start")

        self.assertEqual(kind, "start")
        self.assertIs(resolved, replacement)
        self.assertIsNot(resolved, stale)
        self.assertIs(self.records["right"]["points"]["start"], replacement)

    def test_topology_readback_refreshes_endpoint_wrappers(self):
        stale = self.records["right"]["points"]["start"]
        replacement = FakePoint(
            self.left.end.X, self.left.end.Y, self.left.end.Z)
        self.right.start = replacement

        endpoint_map, open_endpoints = self.ops._geometry_topology(self.records)

        self.assertIsNot(
            self.records["right"]["points"]["start"], stale)
        self.assertIs(
            self.records["right"]["points"]["start"], replacement)
        joined_key = tuple(round(value / 1e-8) for value in (
            self.left.end.X, self.left.end.Y, self.left.end.Z))
        self.assertEqual(
            set(endpoint_map[joined_key]),
            {"left.end", "right.start"})
        self.assertNotIn("left.end", open_endpoints)
        self.assertNotIn("right.start", open_endpoints)

    def test_noncoincident_relations_keep_relation_count_verification(self):
        def add_relation(code):
            self.doc.sketch.relations.append({"code": code})

        self.doc.constraint_handler = add_relation
        result = self.ops._apply_constraint(
            self.doc,
            self.records,
            {"type": "horizontal", "entities": ["left"]})

        self.assertEqual(result["before"], 0)
        self.assertEqual(result["after"], 1)
        self.assertEqual(result["verification"], "relation_count")
        self.assertEqual(self.doc.constraint_calls, ["sgHORIZONTAL2D"])


if __name__ == "__main__":
    unittest.main()

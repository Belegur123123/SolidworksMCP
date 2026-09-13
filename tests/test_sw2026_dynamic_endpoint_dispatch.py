"""Regression coverage for SW2026 zero-argument COM endpoint dispatch.

SOLIDWORKS dynamic pywin32 wrappers can expose ISketchLine.GetStartPoint2 and
GetEndPoint2 as property-like COM values rather than ordinary Python methods.
Calling ``segment.GetStartPoint2()`` can therefore invoke the returned
SketchPoint's default member and fail with DISP_E_MEMBERNOTFOUND, while
``com_get(segment, "GetStartPoint2")`` correctly returns the SketchPoint.
"""

import unittest

from solidworks_mcp.automation import ParametricSketchOperations


class CallablePoint:
    """Model a dynamic COM point that is itself callable but has no default member."""

    def __init__(self, x, y, z=0.0):
        self.X = x
        self.Y = y
        self.Z = z

    def __call__(self):
        raise RuntimeError("DISP_E_MEMBERNOTFOUND")


class DynamicPropertyLine:
    """Model SW2026 dynamic dispatch where zero-arg methods read as properties."""

    def __init__(self, start, end):
        self.GetStartPoint2 = CallablePoint(*start)
        self.GetEndPoint2 = CallablePoint(*end)
        self.ConstructionGeometry = False

    def GetType(self):
        return 0


class Sw2026DynamicEndpointDispatchTests(unittest.TestCase):
    def setUp(self):
        self.ops = ParametricSketchOperations()

    def test_entity_points_reads_property_style_zero_arg_members(self):
        segment = DynamicPropertyLine((0.0, 0.0, 0.0), (0.01, 0.0, 0.0))

        # Reproduce the misleading direct-call diagnostic: the member value is
        # already the point object, so adding () calls the point's default
        # member instead of invoking ISketchLine.GetStartPoint2.
        with self.assertRaisesRegex(RuntimeError, "DISP_E_MEMBERNOTFOUND"):
            segment.GetStartPoint2()

        points = self.ops._entity_points(segment)

        self.assertIs(points["start"], segment.GetStartPoint2)
        self.assertIs(points["end"], segment.GetEndPoint2)
        self.assertEqual(
            (points["start"].X, points["start"].Y, points["start"].Z),
            (0.0, 0.0, 0.0))
        self.assertEqual(
            (points["end"].X, points["end"].Y, points["end"].Z),
            (0.01, 0.0, 0.0))

    def test_refresh_record_points_reacquires_property_style_endpoints(self):
        segment = DynamicPropertyLine((0.0, 0.0, 0.0), (0.01, 0.0, 0.0))
        stale_start = CallablePoint(-1.0, -1.0, 0.0)
        stale_end = CallablePoint(-2.0, -2.0, 0.0)
        record = {
            "object": segment,
            "type": "line",
            "construction": False,
            "points": {"start": stale_start, "end": stale_end},
        }

        points = self.ops._refresh_record_points(record)

        self.assertIs(points["start"], segment.GetStartPoint2)
        self.assertIs(points["end"], segment.GetEndPoint2)
        self.assertIsNot(points["start"], stale_start)
        self.assertIsNot(points["end"], stale_end)
        self.assertIs(record["points"], points)


if __name__ == "__main__":
    unittest.main()

"""Deterministic cut-direction preflight for semantic SOLIDWORKS cuts.

The SOLIDWORKS cut API uses a direction convention that is easy for callers to
misinterpret: for an extruded cut, ``direction_flip=False`` cuts opposite the
sketch normal, while ``direction_flip=True`` reverses that default and cuts
along the sketch normal.

This module adds a read-only geometry preflight and an optional semantic-cut
mode that derives the correct flag from the closed sketch transform and the
scoped semantic bodies before any feature mutation.

The automatic resolver is deliberately conservative.  It succeeds only when
all scoped body bounding boxes lie unambiguously on the same side of the sketch
plane.  If a body spans both sides of the plane, lies within tolerance only, or
multiple scoped bodies disagree, the resolver fails closed instead of guessing.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from mcp.types import Tool

from ..constants import SwErrors
from .com_utils import com_get, dot, transform_point


_DIRECTION_MODES = ("explicit", "auto_material_side")


def register_cut_direction_tools() -> None:
    """Expose the read-only direction resolver and extend semantic_cut schema."""
    from .. import tool_registry

    names = {tool.name for tool in tool_registry.NEW_TOOLS}
    if "resolve_cut_direction" not in names:
        tool_registry.NEW_TOOLS.append(Tool(
            name="resolve_cut_direction",
            description=(
                "Read-only preflight for semantic extruded cuts. Resolves the "
                "closed sketch normal and determines which side of the sketch "
                "plane contains all scoped semantic bodies. For SOLIDWORKS cuts, "
                "material on -normal means direction_flip=false; material on "
                "+normal means direction_flip=true. Fails closed if ambiguous."),
            inputSchema={
                "type": "object",
                "properties": {
                    "scope_body_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Semantic body ids to inspect"},
                    "sketch_name": {
                        "type": "string",
                        "description": "Existing closed sketch feature name"},
                    "direction_tolerance": {
                        "type": "number",
                        "default": 0.01,
                        "description": "Plane-side tolerance in user units"},
                    "unit": {"type": "string"},
                },
                "required": ["scope_body_ids", "sketch_name"],
                "additionalProperties": True,
            },
        ))
    tool_registry.NEW_TOOL_NAMES.add("resolve_cut_direction")

    # semantic_cut is registered by body_identity before this hook runs.  Add
    # the new optional arguments without duplicating the tool or changing its
    # mutability contract.
    for tool in tool_registry.NEW_TOOLS:
        if tool.name != "semantic_cut":
            continue
        props = tool.inputSchema.setdefault("properties", {})
        props["direction_mode"] = {
            "type": "string",
            "enum": list(_DIRECTION_MODES),
            "default": "explicit",
            "description": (
                "explicit uses direction_flip as supplied. auto_material_side "
                "derives the flag before mutation from sketch normal and scoped "
                "body side; prefer this for blind face-sketch cuts.")}
        props["direction_tolerance"] = {
            "type": "number",
            "default": 0.01,
            "description": "Plane-side tolerance in user units for auto mode"}
        break


class CutDirectionOperations:
    """Read-only cut direction resolution plus semantic_cut auto-direction."""

    @staticmethod
    def _bbox_corners(box):
        if not box or len(box) < 6:
            return []
        lo = [float(box[index]) for index in range(3)]
        hi = [float(box[index + 3]) for index in range(3)]
        return [(x, y, z)
                for x in (lo[0], hi[0])
                for y in (lo[1], hi[1])
                for z in (lo[2], hi[2])]

    def _closed_sketch_plane(self, doc, sketch_name: str):
        feature = self._find_feature(doc, sketch_name)
        if feature is None:
            return None, self._error(
                "REFERENCE_MISMATCH",
                f"Sketch '{sketch_name}' not found for cut-direction preflight",
                stage="validate_reference", recoverable=True,
                details={"sketch_name": sketch_name,
                         "existing_features": self._feature_names(doc)})

        sketch = com_get(feature, "GetSpecificFeature2", default=None)
        if sketch is None:
            return None, self._error(
                "REFERENCE_MISMATCH",
                f"Feature '{sketch_name}' is not a readable 2D sketch",
                stage="validate_reference", recoverable=True,
                details={"sketch_name": sketch_name})

        transform = com_get(sketch, "ModelToSketchTransform", default=None)
        data = com_get(transform, "ArrayData", default=None) if transform else None
        inverse = com_get(transform, "Inverse", default=None) if transform else None
        inverse_data = com_get(inverse, "ArrayData", default=None) if inverse else None
        if not data or not inverse_data:
            return None, self._error(
                "REFERENCE_MISMATCH",
                f"Sketch transform for '{sketch_name}' is unavailable",
                stage="validate_reference", recoverable=True,
                details={"sketch_name": sketch_name})

        try:
            basis = self._orientation_basis(data)
            origin = transform_point(inverse_data, (0.0, 0.0, 0.0))
        except Exception as exc:
            return None, self._error(
                "REFERENCE_MISMATCH",
                f"Sketch plane for '{sketch_name}' could not be resolved: {exc}",
                stage="validate_reference", recoverable=True,
                details={"sketch_name": sketch_name})

        return {
            "sketch": sketch,
            "feature": feature,
            "origin_m": tuple(float(value) for value in origin),
            "normal": tuple(float(value) for value in basis["toward_viewer"]),
        }, None

    def resolve_cut_direction(self, scope_body_ids: List[str], sketch_name: str,
                              direction_tolerance: float = 0.01,
                              unit: Optional[str] = None) -> Dict:
        """Determine direction_flip without mutating the SOLIDWORKS document."""
        if not scope_body_ids:
            return self._error(
                "INVALID_PLAN",
                "scope_body_ids must contain at least one body id",
                stage="validate_plan", recoverable=True)
        if not sketch_name:
            return self._error(
                "INVALID_PLAN", "sketch_name is required",
                stage="validate_plan", recoverable=True)
        try:
            tolerance_m = abs(float(self._units.to_meters(
                direction_tolerance, unit)))
        except Exception as exc:
            return self._error(
                "INVALID_PLAN",
                f"Invalid direction_tolerance: {exc}",
                stage="validate_plan", recoverable=True)

        doc, err = self.get_active_doc()
        if err:
            return err
        plane, plane_err = self._closed_sketch_plane(doc, sketch_name)
        if plane_err:
            return plane_err

        normal = plane["normal"]
        origin = plane["origin_m"]
        body_results = []
        sides = set()

        for body_id in scope_body_ids:
            body, identity, resolve_err = self._find_body_by_identity(doc, body_id)
            if resolve_err:
                return resolve_err
            box = com_get(body, "GetBodyBox", default=None)
            corners = self._bbox_corners(box)
            if not corners:
                return self._error(
                    "INVALID_PLAN",
                    f"Body '{identity['current_name']}' has no usable bounding box",
                    stage="validate_geometry", recoverable=True,
                    details={"body_id": body_id,
                             "body_name": identity["current_name"]})

            distances = [dot((corner[0] - origin[0],
                              corner[1] - origin[1],
                              corner[2] - origin[2]), normal)
                         for corner in corners]
            min_distance = min(distances)
            max_distance = max(distances)
            has_negative = min_distance < -tolerance_m
            has_positive = max_distance > tolerance_m

            if has_negative and has_positive:
                return self._error(
                    "INVALID_PLAN",
                    f"Cut direction is ambiguous for '{body_id}': the body "
                    "bounding box spans both sides of the sketch plane",
                    stage="validate_geometry", recoverable=True,
                    recommended_actions=[
                        "Use direction_mode='explicit' with a verified direction, "
                        "or use a face sketch whose scoped body lies entirely on "
                        "one side of the sketch plane."],
                    details={
                        "body_id": body_id,
                        "body_name": identity["current_name"],
                        "min_signed_distance": self._units.from_meters(
                            min_distance, unit),
                        "max_signed_distance": self._units.from_meters(
                            max_distance, unit),
                        "unit": unit or self._units.default_unit.value,
                    })
            if not has_negative and not has_positive:
                return self._error(
                    "INVALID_PLAN",
                    f"Cut direction is ambiguous for '{body_id}': body extent "
                    "is within the sketch-plane tolerance",
                    stage="validate_geometry", recoverable=True,
                    details={"body_id": body_id,
                             "body_name": identity["current_name"],
                             "direction_tolerance": direction_tolerance,
                             "unit": unit or self._units.default_unit.value})

            side = "negative_normal" if has_negative else "positive_normal"
            sides.add(side)
            body_results.append({
                "body_id": body_id,
                "body_name": identity["current_name"],
                "side": side,
                "min_signed_distance": self._units.from_meters(
                    min_distance, unit),
                "max_signed_distance": self._units.from_meters(
                    max_distance, unit),
            })

        if len(sides) != 1:
            return self._error(
                "INVALID_PLAN",
                "Cut direction is ambiguous: scoped bodies lie on different "
                "sides of the sketch plane",
                stage="validate_geometry", recoverable=True,
                details={"scope_body_ids": list(scope_body_ids),
                         "body_sides": body_results})

        material_side = next(iter(sides))
        # SOLIDWORKS cut Direction 1 defaults opposite the sketch normal.
        # Therefore material on -normal uses False; +normal uses True.
        direction_flip = material_side == "positive_normal"
        unit_str = unit or self._units.default_unit.value
        return self._result(
            True,
            f"Cut direction resolved: direction_flip={str(direction_flip).lower()} "
            f"({material_side})",
            SwErrors.swSuccess,
            {
                "direction_flip": direction_flip,
                "material_side": material_side,
                "sketch_name": sketch_name,
                "sketch_origin": [self._units.from_meters(value, unit)
                                  for value in origin],
                "sketch_normal": [round(value, 12) for value in normal],
                "scope_body_ids": list(scope_body_ids),
                "bodies": body_results,
                "direction_tolerance": direction_tolerance,
                "unit": unit_str,
                "method": "closed_sketch_transform_plus_scoped_body_bbox",
                "conservative": True,
                "solidworks_cut_rule": {
                    "direction_flip_false": "opposite_sketch_normal",
                    "direction_flip_true": "along_sketch_normal",
                },
            })

    def semantic_cut(self, scope_body_ids: List[str],
                     sketch_name: str = None,
                     end_condition: str = "blind", depth: float = 10.0,
                     direction_flip: bool = False,
                     direction_mode: str = "explicit",
                     direction_tolerance: float = 0.01,
                     offset_reverse: bool = False,
                     translate_surface: bool = False,
                     start_condition: str = "sketch_plane",
                     start_offset: float = 0.0,
                     flip_start_offset: bool = False,
                     ref_face_ray: Dict = None,
                     start_face_ray: Dict = None,
                     normal_cut: bool = False,
                     optimize_geometry: bool = False,
                     feature_name: str = None,
                     auto_verify: bool = True,
                     auto_flags: bool = False,
                     expected_bbox: Dict = None,
                     expected_merge_bodies: List[str] = None,
                     unit: str = None) -> Dict:
        if direction_mode not in _DIRECTION_MODES:
            return self._error(
                "INVALID_PLAN",
                f"direction_mode must be one of {list(_DIRECTION_MODES)}",
                stage="validate_plan", recoverable=True,
                details={"direction_mode": direction_mode})

        requested_direction = bool(direction_flip)
        preflight = None
        effective_direction = requested_direction
        if direction_mode == "auto_material_side":
            preflight = self.resolve_cut_direction(
                scope_body_ids=scope_body_ids,
                sketch_name=sketch_name,
                direction_tolerance=direction_tolerance,
                unit=unit)
            if not preflight.get("success"):
                return preflight
            effective_direction = bool(
                (preflight.get("data") or {}).get("direction_flip"))

        result = super().semantic_cut(
            scope_body_ids=scope_body_ids,
            sketch_name=sketch_name,
            end_condition=end_condition,
            depth=depth,
            direction_flip=effective_direction,
            offset_reverse=offset_reverse,
            translate_surface=translate_surface,
            start_condition=start_condition,
            start_offset=start_offset,
            flip_start_offset=flip_start_offset,
            ref_face_ray=ref_face_ray,
            start_face_ray=start_face_ray,
            normal_cut=normal_cut,
            optimize_geometry=optimize_geometry,
            feature_name=feature_name,
            auto_verify=auto_verify,
            auto_flags=auto_flags,
            expected_bbox=expected_bbox,
            expected_merge_bodies=expected_merge_bodies,
            unit=unit)

        data = result.setdefault("data", {})
        data["direction_mode"] = direction_mode
        data["requested_direction_flip"] = requested_direction
        data["effective_direction_flip"] = effective_direction
        if preflight is not None:
            data["cut_direction_preflight"] = preflight.get("data", {})
        return result

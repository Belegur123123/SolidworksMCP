"""SOLIDWORKS 2026 parametric-sketch compatibility fixes.

This module subclasses the 6.5.31 parametric backend and narrows the behavioral
changes to topology-changing coincident constraints and SketchPoint lifetime.
It is intentionally separate from the large upstream parametric.py so the fork
can keep upstream changes easy to review and merge.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .com_utils import com_get
from .parametric import (
    RELATION_CODES,
    ParametricSketchOperations as _BaseParametricSketchOperations,
    _SketchValidationError,
)


class ParametricSketchOperations(_BaseParametricSketchOperations):
    """Parametric backend with SW2026-safe coincident verification."""

    def _refresh_record_points(self, record):
        """Re-acquire SketchPoint wrappers from the owning sketch segment.

        A topology-changing relation such as ``sgCOINCIDENT`` can replace one
        of the endpoint COM objects.  The old pywin32 wrapper may then raise
        ``RPC_E_DISCONNECTED`` even though the owning SketchSegment remains
        valid.  Segment-derived point wrappers are therefore refreshed before
        later use.
        """
        segment = record.get("object")
        if segment is None:
            record["points"] = {}
            return record["points"]
        record["points"] = self._entity_points(segment)
        return record["points"]

    @staticmethod
    def _point_xyz_m(point):
        """Return a SketchPoint coordinate tuple in native SOLIDWORKS metres."""
        if point is None:
            return None
        values = []
        for axis in ("X", "Y", "Z"):
            value = com_get(point, axis, default=None)
            if value is None:
                return None
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                return None
        return tuple(values)

    def _resolve_entity_ref(self, records, reference):
        if reference in {"origin", "sketch_origin"}:
            return ("origin", None)
        if not isinstance(reference, str):
            return (None, None)
        entity_id, _, suffix = reference.partition(".")
        record = records.get(entity_id)
        if not record:
            return (None, None)
        if suffix in {"start", "end", "center"}:
            points = self._refresh_record_points(record)
            return (suffix, points.get(suffix))
        return ("entity", record["object"])

    def _verify_coincident_refs(self, records, refs, tolerance_m=1e-8):
        """Geometrically verify point-to-point coincident constraints.

        SOLIDWORKS 2026 can merge two sketch vertices successfully while
        ``RelationManager`` still reports the same relation count.  For point
        references, fresh coordinate read-back is therefore authoritative.
        ``None`` means this constraint shape is not a point-to-point case and
        should fall back to the generic relation-count verification.
        """
        coordinates = []
        for ref in refs:
            kind, obj = self._resolve_entity_ref(records, ref)
            if kind not in {"start", "end", "center"} or obj is None:
                return None
            coords = self._point_xyz_m(obj)
            if coords is None:
                return None
            coordinates.append(coords)
        if len(coordinates) < 2:
            return None
        anchor = coordinates[0]
        max_error_m = max(
            math.dist(anchor, coords) for coords in coordinates[1:])
        return {
            "verified": max_error_m <= float(tolerance_m),
            "max_error_m": max_error_m,
            "tolerance_m": float(tolerance_m),
        }

    def _apply_constraint(self, doc, records, constraint,
                          allow_redundant=False):
        ctype = str(constraint.get("type", "")).lower()
        refs = list(constraint.get("entities", []))
        about = constraint.get("about")
        if about:
            refs.append(about)

        doc.ClearSelection2(True)
        selected = 0
        for ref in refs:
            if ref in {"axis_x", "axis_y"}:
                raise ValueError(
                    f"'{ref}' must be declared as a centerline entity")
            if self._select_reference(doc, records, ref, append=selected > 0):
                selected += 1
        if selected != len(refs):
            raise ValueError(
                f"Could not select all refs for {ctype}: {refs}")

        before = self._active_relation_count(doc)

        # IModelDoc2::SketchAddConstraints is a void API call.  Do not infer
        # success from a pywin32 return value; verify the resulting state.
        doc.SketchAddConstraints(RELATION_CODES[ctype])
        after = self._active_relation_count(doc)

        if ctype == "coincident":
            geometry = self._verify_coincident_refs(records, refs)
            if geometry is not None:
                if not geometry["verified"]:
                    if allow_redundant:
                        return None
                    raise _SketchValidationError(
                        "SKETCH_CONSTRAINT_UNVERIFIED",
                        "Coincident constraint did not produce coincident geometry",
                        details={
                            "constraint_type": ctype,
                            "references": list(refs),
                            "relation_count_before": before,
                            "relation_count_after": after,
                            **geometry,
                        })
                return {
                    "type": ctype,
                    "before": before,
                    "after": after,
                    "verification": "geometry",
                    "relation_count_changed": bool(
                        before is not None and after is not None and
                        after > before),
                    "max_error_m": geometry["max_error_m"],
                    "tolerance_m": geometry["tolerance_m"],
                }

        if (before is not None and after is not None and after <= before):
            if allow_redundant:
                return None
            raise _SketchValidationError(
                "SKETCH_CONSTRAINT_UNVERIFIED",
                f"Constraint '{ctype}' produced no verifiable relation-count change",
                details={
                    "constraint_type": ctype,
                    "references": list(refs),
                    "relation_count_before": before,
                    "relation_count_after": after,
                })

        return {
            "type": ctype,
            "before": before,
            "after": after,
            "verification": (
                "relation_count"
                if before is not None and after is not None
                else "api_no_exception"),
        }

    def _geometry_topology(self, records, tolerance_m=1e-8):
        endpoint_map = defaultdict(list)
        for entity_id, record in records.items():
            if record.get("construction"):
                continue
            points = self._refresh_record_points(record)
            for end_name in ("start", "end"):
                point = points.get(end_name)
                if point is None:
                    continue
                coords = [float(com_get(point, axis, default=0.0))
                          for axis in ("X", "Y", "Z")]
                key = tuple(round(value / tolerance_m) for value in coords)
                endpoint_map[key].append(f"{entity_id}.{end_name}")
        open_endpoints = [refs[0] for refs in endpoint_map.values()
                          if len(refs) % 2 == 1]
        return endpoint_map, open_endpoints

    def _locked_trace_constraints(self, records, constraints):
        # The upstream implementation groups coincident point objects by their
        # coordinates.  Refresh them first so a previous topology-changing
        # constraint cannot leave a disconnected SketchPoint wrapper here.
        for record in records.values():
            self._refresh_record_points(record)
        return super()._locked_trace_constraints(records, constraints)

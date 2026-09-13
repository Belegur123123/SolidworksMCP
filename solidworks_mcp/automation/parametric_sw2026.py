"""SOLIDWORKS 2026 parametric-sketch compatibility fixes.

This module subclasses the 6.5.31 parametric backend and narrows the behavioral
changes to topology-changing coincident constraints, SketchPoint lifetime, and
active-sketch recovery after a SOLIDWORKS rebuild.
It is intentionally separate from the large upstream parametric.py so the fork
can keep upstream changes easy to review and merge.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .com_utils import com_get, select_by_id2
from .parametric import (
    RELATION_CODES,
    ParametricSketchOperations as _BaseParametricSketchOperations,
    _SketchValidationError,
)


class ParametricSketchOperations(_BaseParametricSketchOperations):
    """Parametric backend with SW2026-safe sketch lifecycle handling."""

    def create_parametric_sketch(self, name: str, *args, **kwargs):
        """Expose the sketch name to bounded SW2026 lifecycle recovery.

        ``create_parametric_sketch`` in the upstream backend creates and renames
        the sketch before its one mandatory ``EditRebuild3``.  On SW2026 SP0
        that rebuild can leave the ProfileFeature intact while clearing
        ``SketchManager.ActiveSketch``.  The final Normal-To verification needs
        the intended sketch name so it can reactivate only the sketch owned by
        this atomic operation.
        """
        sentinel = object()
        previous = getattr(
            self, "_sw2026_expected_active_sketch_name", sentinel)
        self._sw2026_expected_active_sketch_name = str(name)
        try:
            return super().create_parametric_sketch(name, *args, **kwargs)
        finally:
            if previous is sentinel:
                try:
                    delattr(self, "_sw2026_expected_active_sketch_name")
                except AttributeError:
                    pass
            else:
                self._sw2026_expected_active_sketch_name = previous

    def _reactivate_expected_sketch(self, doc, sketch_name):
        """Reactivate a known sketch after SW2026 drops the edit context.

        This deliberately does not call ``_activate_sketch_feature`` because
        that helper also performs Normal-To.  Keeping activation and camera
        verification separate prevents a duplicate orientation pass and makes
        the recovery state explicit.
        """
        feature = self._find_sketch_feature(doc, sketch_name)
        if feature is None:
            raise _SketchValidationError(
                "SKETCH_ACTIVE_STATE_LOST",
                f"Sketch '{sketch_name}' disappeared before view verification",
                details={"sketch": sketch_name,
                         "recovery": "feature_not_found"})

        try:
            doc.ClearSelection2(True)
        except Exception:
            pass

        try:
            selected = bool(feature.Select2(False, 0))
        except Exception:
            selected = select_by_id2(doc, sketch_name, "SKETCH")
        if not selected:
            raise _SketchValidationError(
                "SKETCH_ACTIVE_STATE_LOST",
                f"Sketch '{sketch_name}' could not be selected for reactivation",
                details={"sketch": sketch_name,
                         "recovery": "selection_failed"})

        manager = com_get(doc, "SketchManager", default=None)
        if manager is None:
            raise _SketchValidationError(
                "SKETCH_ACTIVE_STATE_LOST",
                "SketchManager is unavailable during sketch reactivation",
                details={"sketch": sketch_name,
                         "recovery": "sketch_manager_unavailable"})
        try:
            manager.InsertSketch(True)
        except Exception as exc:
            raise _SketchValidationError(
                "SKETCH_ACTIVE_STATE_LOST",
                f"Sketch '{sketch_name}' could not be reactivated: {exc}",
                details={"sketch": sketch_name,
                         "recovery": "insert_sketch_failed",
                         "exception": str(exc)}) from exc

        refreshed_doc, active = self._wait_for_active_sketch(doc, 1.0)
        if active is None:
            raise _SketchValidationError(
                "SKETCH_ACTIVE_STATE_LOST",
                f"Sketch '{sketch_name}' did not become active after rebuild",
                details={"sketch": sketch_name,
                         "recovery": "active_sketch_not_published"})

        active_feature = com_get(active, "GetFeature", default=None)
        active_name = str(com_get(
            active_feature, "Name", default="") or "")
        if active_name and active_name != sketch_name:
            raise _SketchValidationError(
                "SKETCH_ACTIVE_STATE_LOST",
                f"Reactivation opened '{active_name}' instead of '{sketch_name}'",
                details={"sketch": sketch_name,
                         "active_sketch": active_name,
                         "recovery": "wrong_sketch_activated"})
        return refreshed_doc, active

    def _auto_normal_to(self, doc, zoom_to_fit=True):
        """Recover the owned sketch edit context before view verification.

        The recovery is intentionally scoped to ``create_parametric_sketch``:
        outside that operation no expected sketch name is installed and view
        behavior remains identical to upstream 6.5.31.
        """
        expected = getattr(
            self, "_sw2026_expected_active_sketch_name", None)
        manager = com_get(doc, "SketchManager", default=None)
        active = com_get(manager, "ActiveSketch", default=None)

        if active is None and expected:
            # During the initial create_sketch() call the requested final name
            # has not been applied yet.  Only recover when that named feature
            # already exists; otherwise preserve the upstream startup behavior.
            feature = self._find_sketch_feature(doc, expected)
            if feature is not None:
                doc, active = self._reactivate_expected_sketch(doc, expected)

        return super()._auto_normal_to(doc, zoom_to_fit=zoom_to_fit)

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
            # Some deterministic unit tests and callers intentionally provide
            # point-only records.  There is no owning COM segment to refresh
            # from in that representation, so retain the supplied points.
            return record.setdefault("points", {})
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
        # coordinates.  Refresh only records backed by a real owning segment;
        # deterministic point-only records have nothing to reacquire from and
        # must preserve their supplied endpoint objects.
        for record in records.values():
            if record.get("object") is not None:
                self._refresh_record_points(record)
        return super()._locked_trace_constraints(records, constraints)

"""Safe mutation of existing SOLIDWORKS driving dimensions.

The high-level sketch API creates dimensions, but later parametric edits need a
separate operation that changes the existing IDimension rather than creating a
replacement.  All zero-argument dynamic COM reads go through ``com_get`` so
SOLIDWORKS 2026 property-style dispatch (for example GetFeatureCount) cannot be
misinterpreted as a Python callable.
"""

from __future__ import annotations

import math
import time
from typing import Dict

from ..constants import SwErrors
from .com_utils import com_get, resolve_solidworks_constant


class DimensionUpdateOperations:
    """Mixin for verified, rollback-safe edits of existing dimensions."""

    @staticmethod
    def _dimension_state_name(state):
        try:
            driving = resolve_solidworks_constant("swDimensionDriving")
            driven = resolve_solidworks_constant("swDimensionDriven")
            unknown = resolve_solidworks_constant("swDimensionDrivenUnknown")
        except LookupError:
            driving, driven, unknown = 2, 1, 0
        return ({driving: "driving", driven: "driven", unknown: "unknown"}
                .get(state, "unknown")), driving

    def set_dimension_value(self, dimension_name: str, value: float,
                            unit: str = None, rebuild: bool = True,
                            rollback_on_failure: bool = True) -> Dict:
        """Change one existing driving dimension and verify the same parameter.

        The operation never creates or deletes a dimension, sketch or feature.
        If the write/rebuild/read-back sequence fails after mutation, the old
        SystemValue is restored and rebuilt once before the error is returned.
        """
        doc, err = self.get_active_doc()
        if err:
            return err

        name = str(dimension_name or "").strip()
        if not name:
            return self._error(
                "SKETCH_UNDERDEFINED", "dimension_name is required",
                details={"dimension_name": dimension_name})

        parameter = com_get(doc, "Parameter", name, default=None)
        if parameter is None:
            return self._error(
                "SKETCH_UNDERDEFINED",
                f"Existing dimension '{name}' was not found",
                recommended_actions=[
                    "Read the exact stored dimension name before updating it."],
                details={"dimension_name": name})

        before_m = com_get(parameter, "SystemValue", default=None)
        before_state = com_get(parameter, "DrivenState", default=None)
        try:
            before_m = float(before_m)
            before_state = int(before_state)
        except (TypeError, ValueError):
            return self._error(
                "COM_MEMBER_MISMATCH",
                f"Dimension '{name}' could not be read safely",
                details={"dimension_name": name,
                         "system_value": before_m,
                         "driven_state": before_state})

        state_name, driving_value = self._dimension_state_name(before_state)
        if before_state != driving_value:
            return self._error(
                "SKETCH_UNDERDEFINED",
                f"Dimension '{name}' is not a driving dimension",
                details={"dimension_name": name,
                         "driven_state": before_state,
                         "driven_state_name": state_name})

        selected_unit = unit or self._units.default_unit.value
        try:
            target_m = self._units.to_meters(float(value), selected_unit)
        except Exception as exc:
            return self._error(
                "COM_MEMBER_MISMATCH",
                f"Invalid dimension value/unit for '{name}': {exc}",
                details={"dimension_name": name, "value": value,
                         "unit": selected_unit})
        if not math.isfinite(target_m):
            return self._error(
                "COM_MEMBER_MISMATCH",
                f"Dimension '{name}' target value is not finite",
                details={"dimension_name": name, "target_m": target_m})

        feature_count_before = com_get(
            doc, "GetFeatureCount", default=None)
        try:
            feature_count_before = (None if feature_count_before is None else
                                    int(feature_count_before))
        except (TypeError, ValueError):
            feature_count_before = None

        tolerance_m = max(1e-10, abs(target_m) * 1e-8)
        rebuild_count = 0
        solver_elapsed = 0.0
        rebuild_return_value = None
        mutated = False

        try:
            parameter.SystemValue = target_m
            mutated = True
            immediate_m = float(com_get(
                parameter, "SystemValue", default=float("nan")))
            if (not math.isfinite(immediate_m) or
                    abs(immediate_m - target_m) > tolerance_m):
                raise RuntimeError(
                    f"Immediate dimension read-back mismatch: "
                    f"{immediate_m} != {target_m}")

            if rebuild:
                solve_start = time.perf_counter()
                rebuild_return_value = com_get(
                    doc, "EditRebuild3", default=None)
                solver_elapsed = time.perf_counter() - solve_start
                rebuild_count = 1
                self.record_rebuild(solver_elapsed)

            # Reacquire by the same stored name after rebuild.  This proves the
            # existing parameter survived instead of being replaced.
            parameter_after = com_get(doc, "Parameter", name, default=None)
            if parameter_after is None:
                raise RuntimeError(
                    "Dimension disappeared after rebuild")
            after_m = float(com_get(
                parameter_after, "SystemValue", default=float("nan")))
            after_state = int(com_get(
                parameter_after, "DrivenState", default=-1))
            if (not math.isfinite(after_m) or
                    abs(after_m - target_m) > tolerance_m):
                raise RuntimeError(
                    f"Post-rebuild dimension read-back mismatch: "
                    f"{after_m} != {target_m}")
            after_state_name, _ = self._dimension_state_name(after_state)
            if after_state != driving_value:
                raise RuntimeError(
                    f"Dimension changed driving state: "
                    f"{before_state} -> {after_state}")

            feature_count_after = com_get(
                doc, "GetFeatureCount", default=None)
            try:
                feature_count_after = (
                    None if feature_count_after is None
                    else int(feature_count_after))
            except (TypeError, ValueError):
                feature_count_after = None
            if (feature_count_before is not None and
                    feature_count_after is not None and
                    feature_count_after != feature_count_before):
                raise RuntimeError(
                    "Feature count changed during a pure dimension update: "
                    f"{feature_count_before} -> {feature_count_after}")

            return self._result(
                True,
                f"Updated dimension '{name}'",
                SwErrors.swSuccess,
                {
                    "dimension_name": name,
                    "before_system_value_m": before_m,
                    "after_system_value_m": after_m,
                    "before_value": self._units.from_meters(
                        before_m, selected_unit),
                    "after_value": self._units.from_meters(
                        after_m, selected_unit),
                    "unit": selected_unit,
                    "driven_state_before": before_state,
                    "driven_state_after": after_state,
                    "driven_state_name_before": state_name,
                    "driven_state_name_after": after_state_name,
                    "driving": True,
                    "rebuild_count": rebuild_count,
                    "solver_time_sec": round(solver_elapsed, 6),
                    "rebuild_return_value": rebuild_return_value,
                    "feature_count_before": feature_count_before,
                    "feature_count_after": feature_count_after,
                    "feature_count_changed": False,
                })
        except Exception as exc:
            restored = None
            rollback_error = None
            if mutated and rollback_on_failure:
                restored = False
                try:
                    rollback_parameter = com_get(
                        doc, "Parameter", name, default=None)
                    if rollback_parameter is None:
                        raise RuntimeError(
                            "Dimension missing during rollback")
                    rollback_parameter.SystemValue = before_m
                    if rebuild:
                        com_get(doc, "EditRebuild3", default=None)
                    verify_parameter = com_get(
                        doc, "Parameter", name, default=None)
                    verify_m = float(com_get(
                        verify_parameter, "SystemValue", default=float("nan")))
                    rollback_tolerance = max(
                        1e-10, abs(before_m) * 1e-8)
                    restored = (math.isfinite(verify_m) and
                                abs(verify_m - before_m) <= rollback_tolerance)
                    if restored:
                        self._runtime.increment("rollbacks")
                except Exception as rollback_exc:
                    rollback_error = str(rollback_exc)

            return self._error(
                "COM_MEMBER_MISMATCH",
                f"Dimension update failed for '{name}': {exc}",
                document_restored=restored,
                recommended_actions=[
                    "Inspect the existing dimension and dependent feature state "
                    "before retrying."],
                details={
                    "dimension_name": name,
                    "before_system_value_m": before_m,
                    "target_system_value_m": target_m,
                    "rebuild_count": rebuild_count,
                    "solver_time_sec": round(solver_elapsed, 6),
                    "feature_count_before": feature_count_before,
                    "rollback_error": rollback_error,
                })

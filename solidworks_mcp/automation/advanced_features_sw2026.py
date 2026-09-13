"""SW2026 safety wrapper for advanced feature operations.

This layer preserves pre-existing feature names when a single-ended scoped cut
causes the SolidWorks body/feature display-name namespace to collide.
SOLIDWORKS 2026 can legitimately refuse to rename the post-cut body back to the
old body name while an older source feature still owns that same name. The
upstream implementation resolved that collision by renaming the source feature.
For parametric models that is the wrong priority: feature names are stable
references, while body names are selection/display handles.

Policy:
- For single-ended scoped cuts, never leave a pre-existing source feature
  renamed by advanced_cut.
- If the requested scoped body name collides with that source feature after the
  cut, move the body to a deterministic ``<old>_Body`` alias (with a numeric
  suffix only when necessary), then restore the source feature's original name.
- Report the body alias explicitly in the result.
- If this repair cannot be verified, delete the newly created cut feature and
  best-effort restore the original names, then return a structured invariant
  failure instead of silently changing the model tree.
- Double-ended cuts retain the upstream body-name-priority contract for backward
  compatibility. That path is already covered by the v6 regression suite and
  is intentionally not changed until the same source-feature-name policy has
  been validated live for double-ended FeatureCut4 operations.
"""

from __future__ import annotations

from typing import Dict, List

from ..constants import SwErrors
from .advanced_features import AdvancedFeatureOperations as _BaseAdvancedFeatures
from .com_utils import com_get
from .runtime import structured_error


class AdvancedFeatureOperations(_BaseAdvancedFeatures):
    """SOLIDWORKS 2026 compatibility/safety additions for advanced features."""

    def _unique_body_alias(self, doc, requested_name: str) -> str:
        """Return a deterministic body alias that does not collide with names."""
        occupied = set(self._body_names(doc)) | set(self._feature_names(doc))
        base = f"{requested_name}_Body"
        candidate = base
        index = 2
        while candidate in occupied:
            candidate = f"{base}_{index}"
            index += 1
        return candidate

    def _rollback_cut_name_policy(self, doc, cut_feature_name: str,
                                  temporary_renames: List[Dict],
                                  body_aliases: List[Dict]) -> Dict:
        """Best-effort rollback when final name preservation cannot be verified."""
        details = {
            "cut_deleted": False,
            "feature_restore_failures": [],
            "body_restore_failures": [],
        }

        cut = self._find_feature(doc, cut_feature_name)
        if cut is not None:
            details["cut_deleted"] = bool(self._delete_feature_object(
                doc, cut, cut_feature_name, delete_absorbed=False))

        for record in reversed(temporary_renames):
            old_name = record.get("from")
            new_name = record.get("to")
            feature = self._find_feature(doc, new_name)
            if feature is None:
                feature = self._find_feature(doc, old_name)
            if feature is None:
                details["feature_restore_failures"].append({
                    "from": new_name,
                    "to": old_name,
                    "reason": "feature_not_found",
                })
                continue
            current = com_get(feature, "Name", default=new_name)
            if current != old_name:
                try:
                    feature.Name = old_name
                except Exception as exc:
                    details["feature_restore_failures"].append({
                        "from": current,
                        "to": old_name,
                        "reason": str(exc),
                    })
                    continue
                actual = com_get(feature, "Name", default=current)
                if actual != old_name:
                    details["feature_restore_failures"].append({
                        "from": current,
                        "to": old_name,
                        "actual_name": actual,
                        "reason": "rename_did_not_stick",
                    })

        for record in reversed(body_aliases):
            old_name = record.get("from")
            alias = record.get("to")
            body = self._find_body(doc, alias)
            if body is None:
                body = self._find_body(doc, old_name)
            if body is None:
                details["body_restore_failures"].append({
                    "from": alias,
                    "to": old_name,
                    "reason": "body_not_found",
                })
                continue
            current = com_get(body, "Name", default=alias)
            if current != old_name:
                try:
                    body.Name = old_name
                except Exception as exc:
                    details["body_restore_failures"].append({
                        "from": current,
                        "to": old_name,
                        "reason": str(exc),
                    })
                    continue
                actual = com_get(body, "Name", default=current)
                if actual != old_name:
                    details["body_restore_failures"].append({
                        "from": current,
                        "to": old_name,
                        "actual_name": actual,
                        "reason": "rename_did_not_stick",
                    })

        details["document_restored"] = bool(
            details["cut_deleted"] and
            not details["feature_restore_failures"] and
            not details["body_restore_failures"])
        return details

    def _preserve_source_feature_names_after_cut(self, doc, result: Dict) -> Dict:
        """Replace temporary source-feature renames with explicit body aliases."""
        if not result.get("success"):
            return result

        data = result.setdefault("data", {})
        temporary = list(data.get("scope_feature_renames") or [])
        collisions = [
            record for record in temporary
            if record.get("reason") == "body_name_namespace_collision"
        ]
        if not collisions:
            data.setdefault("source_feature_names_preserved", True)
            data.setdefault("scope_body_name_changes", [])
            return result

        body_aliases = []
        recoveries = []
        cut_feature_name = data.get("feature_name") or ""

        try:
            for record in collisions:
                original_feature_name = record.get("from")
                temporary_feature_name = record.get("to")
                if not original_feature_name or not temporary_feature_name:
                    raise RuntimeError("invalid scope feature rename record")

                body = self._find_body(doc, original_feature_name)
                if body is None:
                    raise RuntimeError(
                        f"scoped body '{original_feature_name}' not found "
                        "during name stabilization")

                source_feature = self._find_feature(doc, temporary_feature_name)
                if source_feature is None:
                    raise RuntimeError(
                        f"temporarily renamed source feature "
                        f"'{temporary_feature_name}' not found")

                alias = self._unique_body_alias(doc, original_feature_name)
                before_body_name = com_get(
                    body, "Name", default=original_feature_name)
                body.Name = alias
                actual_body_name = com_get(body, "Name", default=before_body_name)
                if actual_body_name != alias:
                    raise RuntimeError(
                        f"body alias rename did not stick: requested '{alias}', "
                        f"actual '{actual_body_name}'")
                body_aliases.append({
                    "from": original_feature_name,
                    "to": alias,
                    "reason": "preserve_existing_feature_name",
                })

                before_feature_name = com_get(
                    source_feature, "Name", default=temporary_feature_name)
                source_feature.Name = original_feature_name
                actual_feature_name = com_get(
                    source_feature, "Name", default=before_feature_name)
                if actual_feature_name != original_feature_name:
                    raise RuntimeError(
                        "source feature name restoration did not stick: "
                        f"requested '{original_feature_name}', "
                        f"actual '{actual_feature_name}'")
                recoveries.append({
                    "from": temporary_feature_name,
                    "to": original_feature_name,
                    "body_alias": alias,
                })

            # Final invariant checks: every original source feature name exists,
            # every temporary source name is gone, and the cut feature remains.
            for record in collisions:
                original = record["from"]
                temporary_name = record["to"]
                if self._find_feature(doc, original) is None:
                    raise RuntimeError(
                        f"source feature '{original}' missing after restoration")
                if self._find_feature(doc, temporary_name) is not None:
                    raise RuntimeError(
                        f"temporary source feature name '{temporary_name}' "
                        "still exists after restoration")
            if cut_feature_name and self._find_feature(doc, cut_feature_name) is None:
                raise RuntimeError(
                    f"cut feature '{cut_feature_name}' missing after name stabilization")

        except Exception as exc:
            rollback = self._rollback_cut_name_policy(
                doc, cut_feature_name, temporary, body_aliases)
            message = (
                "Cut created geometry but could not preserve pre-existing "
                f"feature names: {exc}")
            failure_data = dict(data)
            failure_data.update({
                "temporary_scope_feature_renames": temporary,
                "scope_feature_renames": temporary,
                "scope_body_name_changes": body_aliases,
                "name_policy_rollback": rollback,
                "error": structured_error(
                    "INVARIANT_FAILED",
                    message,
                    stage="validate_invariants",
                    recoverable=True,
                    document_restored=rollback.get("document_restored"),
                    details={
                        "temporary_scope_feature_renames": temporary,
                        "scope_body_name_changes": body_aliases,
                        "rollback": rollback,
                    },
                ),
            })
            return self._result(
                False, message, SwErrors.swFeatureError, failure_data)

        # Preserve the base operation's diagnostic history, but expose the
        # final state unambiguously.
        original_restorations = list(data.get("scope_name_restorations") or [])
        data["temporary_scope_name_restorations"] = original_restorations
        data["temporary_scope_feature_renames"] = temporary
        data["scope_name_restorations"] = []
        data["scope_feature_renames"] = []
        data["scope_feature_rename_recoveries"] = recoveries
        data["scope_body_name_changes"] = body_aliases
        data["source_feature_names_preserved"] = True
        data["body_name_policy"] = (
            "preserve_feature_name_alias_body_on_collision")
        data["body_names_after"] = self._body_names(doc)
        data["bodies_after"] = len(data["body_names_after"])
        # This is a display-name transition, not a topology change.
        data["merged_bodies"] = []
        data["new_bodies"] = []

        alias_summary = ", ".join(
            f"{entry['from']} -> {entry['to']}" for entry in body_aliases)
        result["message"] = (
            f"{result.get('message', '').rstrip()} "
            f"[preserved source feature names; body alias: {alias_summary}]"
        ).strip()
        return result

    def advanced_cut(self, sketch_name: str = None,
                     end_condition: str = "blind",
                     depth: float = 10.0,
                     direction_flip: bool = False,
                     offset_reverse: bool = False,
                     translate_surface: bool = False,
                     start_condition: str = "sketch_plane",
                     start_offset: float = 0.0,
                     flip_start_offset: bool = False,
                     ref_face_ray: Dict = None,
                     start_face_ray: Dict = None,
                     scope_bodies: List[str] = None,
                     normal_cut: bool = False,
                     optimize_geometry: bool = False,
                     feature_name: str = None,
                     auto_verify: bool = True,
                     auto_flags: bool = False,
                     expected_bbox: Dict = None,
                     expected_merge_bodies: List[str] = None,
                     unit: str = None) -> Dict:
        """Run the native cut, then enforce the SW2026 naming policy.

        Single-ended cuts get source-feature-name preservation. Double-ended
        cuts retain the established upstream body-name-priority contract until
        that path is separately live-validated under the stricter policy.
        """
        result = super().advanced_cut(
            sketch_name=sketch_name,
            end_condition=end_condition,
            depth=depth,
            direction_flip=direction_flip,
            offset_reverse=offset_reverse,
            translate_surface=translate_surface,
            start_condition=start_condition,
            start_offset=start_offset,
            flip_start_offset=flip_start_offset,
            ref_face_ray=ref_face_ray,
            start_face_ray=start_face_ray,
            scope_bodies=scope_bodies,
            normal_cut=normal_cut,
            optimize_geometry=optimize_geometry,
            feature_name=feature_name,
            auto_verify=auto_verify,
            auto_flags=auto_flags,
            expected_bbox=expected_bbox,
            expected_merge_bodies=expected_merge_bodies,
            unit=unit,
        )
        if not result.get("success"):
            return result

        data = result.setdefault("data", {})
        if data.get("double_ended"):
            data.setdefault(
                "source_feature_names_preserved",
                not bool(data.get("scope_feature_renames")))
            data.setdefault("scope_body_name_changes", [])
            data.setdefault(
                "body_name_policy",
                "legacy_body_name_priority_double_ended")
            return result

        doc, err = self.get_active_doc()
        if err:
            return err
        return self._preserve_source_feature_names_after_cut(doc, result)

    def get_feature_status(self, name: str) -> Dict:
        """Classify a missing feature as lookup failure, not COM mismatch."""
        result = super().get_feature_status(name)
        if result.get("success"):
            return result
        message = str(result.get("message", ""))
        if message == f"Feature '{name}' not found":
            data = result.setdefault("data", {})
            data["error"] = structured_error(
                "FEATURE_NOT_FOUND",
                message,
                stage="lookup",
                recoverable=True,
                details={
                    "feature_name": name,
                    "existing_features": data.get("existing_features", []),
                    "legacy_error_code": result.get("error_code"),
                    "legacy_error_name": result.get("error_name"),
                },
            )
        return result

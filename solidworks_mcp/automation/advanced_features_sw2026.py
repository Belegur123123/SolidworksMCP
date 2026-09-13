"""SW2026 safety wrapper for advanced feature operations.

This layer preserves pre-existing feature names when a scoped cut causes the
SolidWorks body/feature display-name namespace to collide. SOLIDWORKS 2026 can
legitimately refuse to rename the post-cut body back to the old body name while
an older source feature still owns that same name. The upstream implementation
resolved that collision by renaming the source feature. For parametric models
that is the wrong priority: feature names are stable references, while body
names are selection/display handles.

Policy:
- Never leave a pre-existing source feature renamed by advanced_cut.
- If the requested scoped body name collides with that source feature after the
  cut, move the body to a deterministic ``<old>_Body`` alias (with a numeric
  suffix only when necessary), then restore the source feature's original name.
- Report the body alias explicitly in the result.
- If this repair cannot be verified, delete the newly created cut feature and
  best-effort restore the original names, then return a structured invariant
  failure instead of silently changing the model tree.
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
            feature = (self._find_feature(doc, new_name) or
                       self._find_feature(doc, old_name))
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
            body = self._find_body(doc, alias) or self._find_body(doc, old_name)
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

    def advanced_cut(self, *args, **kwargs) -> Dict:
        """Run the native cut, then enforce source-feature name stability."""
        result = super().advanced_cut(*args, **kwargs)
        if not result.get("success"):
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

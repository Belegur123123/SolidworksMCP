"""Production hardening for semantic solid-body identity resolution.

The core identity contract lives in body_identity.py.  This wrapper makes two
additional guarantees important for long-lived complex models:

- the persisted canonical B_* name is authoritative over stale session state;
- noncanonical/session-only identities cannot be used as a semantic cut scope.

It also separates per-session recovery records by active SOLIDWORKS
configuration so a signature learned in one configuration cannot be reused in
another.  Optional semantic-cut auto direction remains inside this resilient
mutation boundary and consumes the read-only cut-direction resolver.
"""

from __future__ import annotations

from typing import Dict, List

from .body_identity import BodyIdentityOperations as _BaseBodyIdentityOperations
from .com_utils import com_get


_DIRECTION_MODES = ("explicit", "auto_material_side")


class BodyIdentityOperations(_BaseBodyIdentityOperations):
    """Resilient identity resolver used by the public automation class."""

    def _identity_document_key(self, doc) -> str:
        path = str(self._get_doc_path(doc) or "").strip()
        base = path.lower() if path else f"unsaved:{self._get_doc_title(doc)}"
        configuration = ""
        try:
            manager = com_get(doc, "ConfigurationManager", default=None)
            active = (com_get(manager, "ActiveConfiguration", default=None)
                      if manager is not None else None)
            configuration = str(com_get(active, "Name", default="") or "")
        except Exception:
            configuration = ""
        return f"{base}::config:{configuration.lower()}"

    def _find_body_by_identity(self, doc, body_id: str):
        """Resolve canonical persistence first, then verified session recovery.

        A session-registry name is never trusted just because the same string is
        present later.  If a signature was recorded, the candidate must still
        match it; this prevents an old name from resolving to a different body
        after topology/naming changes.
        """
        canonical, err = self._canonical_body_name(body_id)
        if err:
            return None, None, err
        doc_key = self._identity_document_key(doc)
        record = self._identity_registry().get((doc_key, body_id))

        # Durable native state is authoritative across rebuilds/restarts.
        body = self._find_body(doc, canonical)
        if body is not None:
            updated = self._record_body_identity(
                doc, body_id, body,
                role=(record or {}).get("role"),
                source="canonical_name")
            updated["resolved_by"] = "canonical_name"
            return body, updated, None

        # Session current-name fallback is accepted only if it still represents
        # the body whose signature was recorded.  Noncanonical registrations
        # without a signature cannot occur through the public registration path.
        if record:
            current = record.get("current_name")
            if current:
                candidate = self._find_body(doc, current)
                if candidate is not None:
                    expected = record.get("signature")
                    if not expected or self._signature_matches(expected, candidate):
                        updated = self._record_body_identity(
                            doc, body_id, candidate, role=record.get("role"),
                            source="session_registry")
                        updated["resolved_by"] = "session_registry"
                        return candidate, updated, None

        # Last-resort recovery within the same MCP session only. Ambiguity is
        # a hard failure; geometry resemblance is never used to guess.
        if record and record.get("signature"):
            matches = [candidate for candidate in self._get_solid_bodies(doc)
                       if self._signature_matches(record["signature"], candidate)]
            if len(matches) == 1:
                body = matches[0]
                updated = self._record_body_identity(
                    doc, body_id, body, role=record.get("role"),
                    source="geometry_signature")
                updated["resolved_by"] = "geometry_signature"
                return body, updated, None
            if len(matches) > 1:
                return None, None, self._error(
                    "REFERENCE_MISMATCH",
                    f"Logical body id '{body_id}' is ambiguous: "
                    f"{len(matches)} bodies match the stored geometry signature",
                    stage="validate_reference", recoverable=True,
                    details={
                        "body_id": body_id,
                        "canonical_name": canonical,
                        "candidate_names": [com_get(
                            candidate, "Name", default="?")
                            for candidate in matches],
                    })

        return None, None, self._error(
            "REFERENCE_MISMATCH",
            f"Logical body id '{body_id}' could not be resolved",
            stage="validate_reference", recoverable=True,
            details={
                "body_id": body_id,
                "canonical_name": canonical,
                "existing_bodies": self._body_names(doc),
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
        """Reject unsafe scope and optionally resolve direction before mutation."""
        if not scope_body_ids:
            return self._error(
                "INVALID_PLAN", "scope_body_ids must contain at least one body id",
                stage="validate_plan", recoverable=True)
        if direction_mode not in _DIRECTION_MODES:
            return self._error(
                "INVALID_PLAN",
                f"direction_mode must be one of {list(_DIRECTION_MODES)}",
                stage="validate_plan", recoverable=True,
                details={"direction_mode": direction_mode})

        if direction_mode == "auto_material_side" and (
                auto_flags or start_condition != "sketch_plane"
                or start_offset != 0.0 or start_face_ray is not None):
            return self._error(
                "INVALID_PLAN",
                "auto_material_side requires auto_flags=false and an unshifted "
                "sketch-plane start; use explicit mode for other start conditions",
                stage="validate_plan", recoverable=True)

        doc, err = self.get_active_doc()
        if err:
            return err
        scope_preflight = []
        for body_id in scope_body_ids:
            _, record, resolve_err = self._find_body_by_identity(doc, body_id)
            if resolve_err:
                return resolve_err
            scope_preflight.append(record)
            if record.get("current_name") != record.get("canonical_name"):
                return self._error(
                    "REFERENCE_MISMATCH",
                    f"Semantic cut requires durable canonical identity for "
                    f"'{body_id}', got '{record.get('current_name')}'",
                    stage="validate_reference", recoverable=True,
                    recommended_actions=[
                        "Call register_body_identity with rename_to_canonical=true "
                        "before mutating the body."],
                    details={"body_id": body_id, "identity": record})

        requested_direction = bool(direction_flip)
        effective_direction = requested_direction
        direction_preflight = None
        if direction_mode == "auto_material_side":
            resolver = getattr(self, "resolve_cut_direction", None)
            if resolver is None:
                return self._error(
                    "CAPABILITY_UNAVAILABLE",
                    "Automatic cut-direction resolver is not available",
                    stage="capability", recoverable=False,
                    details={"direction_mode": direction_mode})
            direction_preflight = resolver(
                scope_body_ids=scope_body_ids,
                sketch_name=sketch_name,
                direction_tolerance=direction_tolerance,
                unit=unit)
            if not direction_preflight.get("success"):
                return direction_preflight
            resolved_direction = (direction_preflight.get("data") or {}).get(
                "direction_flip")
            if type(resolved_direction) is not bool:
                return self._error(
                    "INVARIANT_FAILED",
                    "Cut-direction preflight did not return a boolean direction",
                    stage="validate_invariants", recoverable=False)
            effective_direction = resolved_direction

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
            unit=unit,
        )

        data = result.setdefault("data", {})
        data["direction_mode"] = direction_mode
        data["requested_direction_flip"] = requested_direction
        data["effective_direction_flip"] = effective_direction
        if direction_preflight is not None:
            data["cut_direction_preflight"] = direction_preflight.get("data", {})
        if result.get("success"):
            data["semantic_scope_preflight"] = scope_preflight
        return result

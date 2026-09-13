"""Semantic body identity for durable SOLIDWORKS automation.

Names are useful labels, not sufficient identity.  This layer introduces a
small production-oriented identity contract for solid bodies without depending
on unsafe mass persistent-reference reads on SW2026 dirty documents.

A logical id uses ``body:<lower_snake_case>`` and maps deterministically to a
persisted SOLIDWORKS body name ``B_<lower_snake_case>``.  That name survives
Save/Close/Reopen, so a new MCP process can rehydrate the logical id directly
from the model.  During one MCP session a registry also keeps the current name,
semantic role and a light-weight geometry signature for verified recovery after
an unexpected display-name change.

The existing advanced_extrude/advanced_cut tools stay backward compatible.
New semantic_extrude/semantic_cut tools are the production path: feature names
and body names occupy separate namespaces and cuts scope by logical body id.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from mcp.types import Tool

from ..constants import SwErrors
from .com_utils import com_get
from .runtime import structured_error


_BODY_ID_RE = re.compile(r"^body:([a-z0-9][a-z0-9_]{0,63})$")


def _identity_tool(name: str, description: str, properties=None,
                   required=None) -> Tool:
    return Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": True,
        },
    )


def register_identity_tools() -> None:
    """Register semantic identity tools with the existing v6 tool registry.

    server.py imports ``solidworks_mcp.automation`` before importing
    ``tool_registry``.  Registration here therefore extends the existing tool
    list without duplicating or rewriting the large server dispatch table.
    The operation is idempotent so unit tests and reloads are safe.
    """
    from .. import tool_registry

    tools = [
        _identity_tool(
            "register_body_identity",
            "Migrate/register an existing solid body under a durable logical "
            "id. body:insert_main maps to persisted body name B_insert_main. "
            "The rename is verified and pre-existing feature names must remain "
            "unchanged.",
            {
                "body_id": {"type": "string",
                            "description": "Logical id body:<lower_snake_case>"},
                "body_name": {"type": "string",
                              "description": "Current SOLIDWORKS body name; omit when already canonical"},
                "role": {"type": "string",
                         "description": "Optional semantic role, e.g. main_insert_body"},
                "rename_to_canonical": {"type": "boolean", "default": True},
            },
            ["body_id"],
        ),
        _identity_tool(
            "resolve_body_identity",
            "Resolve a logical body id to the current SOLIDWORKS body using "
            "the canonical persisted name first and the session registry / "
            "geometry signature only as verified fallbacks.",
            {"body_id": {"type": "string"}},
            ["body_id"],
        ),
        _identity_tool(
            "list_body_identities",
            "List registered and inferable semantic solid-body identities in "
            "the active part. Canonical B_* names rehydrate across MCP restarts.",
        ),
        _identity_tool(
            "semantic_extrude",
            "Production Boss-Extrude path that creates/attaches a durable "
            "logical body id and enforces a separate B_* body namespace. "
            "Use F_* feature names and S_* sketch names for new production models.",
            {
                "body_id": {"type": "string",
                            "description": "Required logical body id body:<lower_snake_case>"},
                "role": {"type": "string"},
                "sketch_name": {"type": "string"},
                "end_condition": {"type": "string", "default": "blind"},
                "depth": {"type": "number", "default": 10},
                "direction_flip": {"type": "boolean", "default": False},
                "offset_reverse": {"type": "boolean", "default": False},
                "translate_surface": {"type": "boolean", "default": False},
                "merge": {"type": "boolean", "default": True},
                "start_condition": {"type": "string", "default": "sketch_plane"},
                "start_offset": {"type": "number", "default": 0},
                "flip_start_offset": {"type": "boolean", "default": False},
                "ref_face_ray": {"type": "object"},
                "start_face_ray": {"type": "object"},
                "feature_name": {"type": "string"},
                "auto_verify": {"type": "boolean", "default": True},
                "auto_flags": {"type": "boolean", "default": False},
                "expected_bbox": {"type": "object"},
                "expected_merge_bodies": {"type": "array",
                                           "items": {"type": "string"}},
                "unit": {"type": "string"},
            },
            ["body_id"],
        ),
        _identity_tool(
            "semantic_cut",
            "Production Cut-Extrude path scoped by durable logical body ids. "
            "Logical ids are resolved before mutation and must resolve to the "
            "same canonical bodies after the cut or the created feature is rolled back.",
            {
                "scope_body_ids": {"type": "array",
                                   "items": {"type": "string"},
                                   "description": "Logical body ids to cut"},
                "sketch_name": {"type": "string"},
                "end_condition": {"type": "string", "default": "blind"},
                "depth": {"type": "number", "default": 10},
                "direction_flip": {"type": "boolean", "default": False},
                "offset_reverse": {"type": "boolean", "default": False},
                "translate_surface": {"type": "boolean", "default": False},
                "start_condition": {"type": "string", "default": "sketch_plane"},
                "start_offset": {"type": "number", "default": 0},
                "flip_start_offset": {"type": "boolean", "default": False},
                "ref_face_ray": {"type": "object"},
                "start_face_ray": {"type": "object"},
                "normal_cut": {"type": "boolean", "default": False},
                "optimize_geometry": {"type": "boolean", "default": False},
                "feature_name": {"type": "string"},
                "auto_verify": {"type": "boolean", "default": True},
                "auto_flags": {"type": "boolean", "default": False},
                "expected_bbox": {"type": "object"},
                "expected_merge_bodies": {"type": "array",
                                           "items": {"type": "string"}},
                "unit": {"type": "string"},
            },
            ["scope_body_ids"],
        ),
    ]

    existing = {tool.name for tool in tool_registry.NEW_TOOLS}
    for tool in tools:
        if tool.name not in existing:
            tool_registry.NEW_TOOLS.append(tool)
            existing.add(tool.name)

    names = {tool.name for tool in tools}
    tool_registry.NEW_TOOL_NAMES.update(names)
    tool_registry.MUTATING_TOOLS.update({
        "register_body_identity", "semantic_extrude", "semantic_cut"})
    tool_registry.FIRST_GEOMETRY_TOOLS.update({
        "semantic_extrude", "semantic_cut"})
    # Resolve/list are intentionally read-only and therefore not added to
    # MUTATING_TOOLS.


class BodyIdentityOperations:
    """Durable logical identity and semantic feature wrappers for solid bodies."""

    # ------------------------------------------------------------------
    # Identity primitives
    # ------------------------------------------------------------------

    def _parse_body_id(self, body_id: str) -> Tuple[Optional[str], Optional[Dict]]:
        match = _BODY_ID_RE.fullmatch(str(body_id or ""))
        if not match:
            return None, self._error(
                "INVALID_PLAN",
                "body_id must match body:<lower_snake_case> (max 64 key chars)",
                stage="validate_plan", recoverable=True,
                details={"body_id": body_id})
        return match.group(1), None

    def _canonical_body_name(self, body_id: str) -> Tuple[Optional[str], Optional[Dict]]:
        key, err = self._parse_body_id(body_id)
        if err:
            return None, err
        return f"B_{key}", None

    def _identity_document_key(self, doc) -> str:
        path = str(self._get_doc_path(doc) or "").strip()
        if path:
            return path.lower()
        return f"unsaved:{self._get_doc_title(doc)}"

    def _identity_registry(self) -> Dict:
        registry = getattr(self._runtime, "body_identities", None)
        if registry is None:
            registry = {}
            setattr(self._runtime, "body_identities", registry)
        return registry

    def _body_signature(self, body) -> Dict:
        box = com_get(body, "GetBodyBox", default=None)
        bbox = None
        if box and len(box) >= 6:
            bbox = [round(float(v), 12) for v in box[:6]]
        face_count = com_get(body, "GetFaceCount", default=None)
        try:
            face_count = int(face_count) if face_count is not None else None
        except Exception:
            face_count = None
        return {"bbox_m": bbox, "face_count": face_count}

    def _signature_matches(self, expected: Dict, body) -> bool:
        if not expected:
            return False
        actual = self._body_signature(body)
        if (expected.get("face_count") is not None and
                actual.get("face_count") != expected.get("face_count")):
            return False
        a = actual.get("bbox_m")
        b = expected.get("bbox_m")
        if not a or not b or len(a) != 6 or len(b) != 6:
            return False
        return all(abs(float(x) - float(y)) <= 1e-9 for x, y in zip(a, b))

    def _record_body_identity(self, doc, body_id: str, body,
                              role: str = None, source: str = "explicit") -> Dict:
        canonical, _ = self._canonical_body_name(body_id)
        current_name = com_get(body, "Name", default=canonical)
        record = {
            "logical_id": body_id,
            "kind": "body",
            "canonical_name": canonical,
            "current_name": current_name,
            "role": role,
            "source": source,
            "signature": self._body_signature(body),
            # v6.5.6 established that mass GetPersistReference3 reads can block
            # on dirty SW2026 documents.  Durable identity therefore uses the
            # persisted canonical B_* name; targeted persistent refs remain a
            # future opt-in optimization, not a correctness dependency.
            "persistent_reference": None,
            "persistent_reference_policy": "disabled_by_default_sw2026_dirty_doc_risk",
        }
        self._identity_registry()[(self._identity_document_key(doc), body_id)] = record
        return dict(record)

    def _find_body_by_identity(self, doc, body_id: str):
        canonical, err = self._canonical_body_name(body_id)
        if err:
            return None, None, err
        doc_key = self._identity_document_key(doc)
        record = self._identity_registry().get((doc_key, body_id))

        if record:
            current = record.get("current_name")
            if current:
                body = self._find_body(doc, current)
                if body is not None:
                    updated = self._record_body_identity(
                        doc, body_id, body, role=record.get("role"),
                        source="session_registry")
                    updated["resolved_by"] = "session_registry"
                    return body, updated, None

        body = self._find_body(doc, canonical)
        if body is not None:
            updated = self._record_body_identity(
                doc, body_id, body,
                role=(record or {}).get("role"),
                source="canonical_name")
            updated["resolved_by"] = "canonical_name"
            return body, updated, None

        # Recovery only within the same MCP session.  A geometry signature is
        # not sufficient to establish identity when more than one body matches.
        if record and record.get("signature"):
            matches = [body for body in self._get_solid_bodies(doc)
                       if self._signature_matches(record["signature"], body)]
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
                    details={"body_id": body_id,
                             "canonical_name": canonical,
                             "candidate_names": [com_get(
                                 candidate, "Name", default="?")
                                 for candidate in matches]})

        return None, None, self._error(
            "REFERENCE_MISMATCH",
            f"Logical body id '{body_id}' could not be resolved",
            stage="validate_reference", recoverable=True,
            details={"body_id": body_id,
                     "canonical_name": canonical,
                     "existing_bodies": self._body_names(doc)})

    def _assign_identity_to_body(self, doc, body_id: str, body,
                                 role: str = None) -> Tuple[Optional[Dict], Optional[Dict]]:
        canonical, err = self._canonical_body_name(body_id)
        if err:
            return None, err

        current = com_get(body, "Name", default=None)
        if current != canonical:
            other = self._find_body(doc, canonical)
            if other is not None and other is not body:
                return None, self._error(
                    "INVARIANT_FAILED",
                    f"Cannot assign '{body_id}': body name '{canonical}' is already in use",
                    stage="validate_invariants", recoverable=True,
                    details={"body_id": body_id, "canonical_name": canonical})
            blocking_feature = self._find_feature(doc, canonical)
            if blocking_feature is not None:
                return None, self._error(
                    "INVARIANT_FAILED",
                    f"Cannot assign '{body_id}': feature name '{canonical}' "
                    "collides with the semantic body namespace",
                    stage="validate_invariants", recoverable=True,
                    details={"body_id": body_id, "canonical_name": canonical})

            features_before = list(self._feature_names(doc))
            try:
                body.Name = canonical
            except Exception as exc:
                return None, self._error(
                    "INVARIANT_FAILED",
                    f"Body rename to semantic name '{canonical}' failed: {exc}",
                    stage="validate_invariants", recoverable=True,
                    details={"body_id": body_id, "from": current,
                             "to": canonical})
            actual = com_get(body, "Name", default=current)
            if actual != canonical:
                return None, self._error(
                    "INVARIANT_FAILED",
                    f"Body rename to semantic name '{canonical}' did not stick",
                    stage="validate_invariants", recoverable=True,
                    details={"body_id": body_id, "from": current,
                             "to": canonical, "actual": actual})
            features_after = list(self._feature_names(doc))
            if features_after != features_before:
                # Do not silently accept body-name changes that mutate feature
                # identity. Revert the body name if possible and fail closed.
                try:
                    body.Name = current
                except Exception:
                    pass
                return None, self._error(
                    "INVARIANT_FAILED",
                    "Assigning a semantic body name unexpectedly changed the feature tree",
                    stage="validate_invariants", recoverable=True,
                    details={"body_id": body_id, "from": current,
                             "to": canonical,
                             "features_before": features_before,
                             "features_after": features_after})

        return self._record_body_identity(
            doc, body_id, body, role=role, source="semantic_assignment"), None

    def _rollback_semantic_feature(self, doc, result: Dict) -> Dict:
        feature_name = (result.get("data") or {}).get("feature_name")
        deleted = False
        if feature_name:
            feature = self._find_feature(doc, feature_name)
            if feature is not None:
                deleted = bool(self._delete_feature_object(
                    doc, feature, feature_name, delete_absorbed=False))
        return {"feature_name": feature_name, "feature_deleted": deleted}

    # ------------------------------------------------------------------
    # Public identity tools
    # ------------------------------------------------------------------

    def register_body_identity(self, body_id: str, body_name: str = None,
                               role: str = None,
                               rename_to_canonical: bool = True) -> Dict:
        doc, err = self.get_active_doc()
        if err:
            return err
        canonical, err = self._canonical_body_name(body_id)
        if err:
            return err
        lookup = body_name or canonical
        body = self._find_body(doc, lookup)
        if body is None:
            return self._error(
                "REFERENCE_MISMATCH",
                f"Body '{lookup}' not found for logical id '{body_id}'",
                stage="validate_reference", recoverable=True,
                details={"body_id": body_id, "body_name": lookup,
                         "existing_bodies": self._body_names(doc)})

        if rename_to_canonical:
            record, assign_err = self._assign_identity_to_body(
                doc, body_id, body, role=role)
            if assign_err:
                return assign_err
        else:
            record = self._record_body_identity(
                doc, body_id, body, role=role, source="explicit_noncanonical")

        return self._result(
            True,
            f"Body identity '{body_id}' -> '{record['current_name']}' registered",
            SwErrors.swSuccess,
            {"identity": record,
             "canonical_name": canonical,
             "renamed": lookup != record["current_name"]})

    def resolve_body_identity(self, body_id: str) -> Dict:
        doc, err = self.get_active_doc()
        if err:
            return err
        body, record, resolve_err = self._find_body_by_identity(doc, body_id)
        if resolve_err:
            return resolve_err
        return self._result(
            True,
            f"Body identity '{body_id}' resolved to '{record['current_name']}'",
            SwErrors.swSuccess,
            {"identity": record,
             "body_name": com_get(body, "Name", default=record["current_name"])})

    def list_body_identities(self) -> Dict:
        doc, err = self.get_active_doc()
        if err:
            return err
        doc_key = self._identity_document_key(doc)
        registry = self._identity_registry()
        items = {}

        for (key, body_id), record in list(registry.items()):
            if key != doc_key:
                continue
            body = self._find_body(doc, record.get("current_name"))
            if body is not None:
                items[body_id] = self._record_body_identity(
                    doc, body_id, body, role=record.get("role"),
                    source="session_registry")

        # Rehydrate durable identities from persisted canonical names after an
        # MCP/SOLIDWORKS session restart.
        for body in self._get_solid_bodies(doc):
            name = str(com_get(body, "Name", default=""))
            if not name.startswith("B_"):
                continue
            key = name[2:]
            if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,63}", key):
                continue
            body_id = f"body:{key}"
            if body_id not in items:
                items[body_id] = self._record_body_identity(
                    doc, body_id, body, source="canonical_name_inference")

        ordered = [items[key] for key in sorted(items)]
        return self._result(
            True, f"{len(ordered)} semantic body identity(ies)",
            SwErrors.swSuccess,
            {"identities": ordered, "count": len(ordered),
             "document_key": doc_key})

    # ------------------------------------------------------------------
    # Production semantic feature paths
    # ------------------------------------------------------------------

    def semantic_extrude(self, body_id: str, role: str = None,
                         sketch_name: str = None,
                         end_condition: str = "blind", depth: float = 10.0,
                         direction_flip: bool = False,
                         offset_reverse: bool = False,
                         translate_surface: bool = False,
                         merge: bool = True,
                         start_condition: str = "sketch_plane",
                         start_offset: float = 0.0,
                         flip_start_offset: bool = False,
                         ref_face_ray: Dict = None,
                         start_face_ray: Dict = None,
                         feature_name: str = None,
                         auto_verify: bool = True,
                         auto_flags: bool = False,
                         expected_bbox: Dict = None,
                         expected_merge_bodies: List[str] = None,
                         unit: str = None) -> Dict:
        canonical, err = self._canonical_body_name(body_id)
        if err:
            return err
        if feature_name and feature_name == canonical:
            return self._error(
                "INVALID_PLAN",
                "Feature and semantic body names must be distinct. "
                f"Use e.g. feature_name='F_{canonical[2:]}' with body_id='{body_id}'.",
                stage="validate_plan", recoverable=True,
                details={"body_id": body_id, "canonical_body_name": canonical,
                         "feature_name": feature_name})

        doc, doc_err = self.get_active_doc()
        if doc_err:
            return doc_err
        bodies_before = list(self._body_names(doc))

        result = self.advanced_extrude(
            sketch_name=sketch_name,
            end_condition=end_condition,
            depth=depth,
            direction_flip=direction_flip,
            offset_reverse=offset_reverse,
            translate_surface=translate_surface,
            merge=merge,
            start_condition=start_condition,
            start_offset=start_offset,
            flip_start_offset=flip_start_offset,
            ref_face_ray=ref_face_ray,
            start_face_ray=start_face_ray,
            feature_name=feature_name,
            auto_verify=auto_verify,
            auto_flags=auto_flags,
            expected_bbox=expected_bbox,
            expected_merge_bodies=expected_merge_bodies,
            unit=unit)
        if not result.get("success"):
            return result

        data = result.setdefault("data", {})
        after_names = list(self._body_names(doc))
        new_names = [name for name in after_names if name not in bodies_before]
        body = None
        resolution = None
        if len(new_names) == 1:
            body = self._find_body(doc, new_names[0])
            resolution = "single_new_body"
        elif len(bodies_before) == 0 and len(after_names) == 1:
            body = self._find_body(doc, after_names[0])
            resolution = "single_initial_body"
        else:
            existing, record, _ = self._find_body_by_identity(doc, body_id)
            if existing is not None:
                body = existing
                resolution = "preexisting_semantic_body"

        if body is None:
            rollback = self._rollback_semantic_feature(doc, result)
            message = (
                f"Extrude succeeded but target body for '{body_id}' is ambiguous")
            data.update({
                "semantic_identity_rollback": rollback,
                "error": structured_error(
                    "INVARIANT_FAILED", message,
                    stage="validate_invariants", recoverable=True,
                    document_restored=rollback.get("feature_deleted"),
                    details={"body_id": body_id,
                             "bodies_before": bodies_before,
                             "bodies_after": after_names,
                             "new_body_names": new_names,
                             "rollback": rollback})})
            return self._result(False, message, SwErrors.swFeatureError, data)

        record, assign_err = self._assign_identity_to_body(
            doc, body_id, body, role=role)
        if assign_err:
            rollback = self._rollback_semantic_feature(doc, result)
            failure_data = dict(data)
            failure_data.update({
                "semantic_identity_rollback": rollback,
                "identity_error": (assign_err.get("data") or {}).get("error")})
            return self._result(
                False,
                f"Extrude geometry created but semantic identity '{body_id}' "
                "could not be committed",
                SwErrors.swFeatureError,
                failure_data)

        data["body_identity"] = record
        data["body_identity_resolution"] = resolution
        data["body_names_after"] = self._body_names(doc)
        data["semantic_naming"] = {
            "sketch_prefix": "S_", "feature_prefix": "F_", "body_prefix": "B_"}
        result["message"] = (
            f"{result.get('message', '').rstrip()} "
            f"[body {body_id} -> {record['current_name']}]").strip()
        return result

    def semantic_cut(self, scope_body_ids: List[str],
                     sketch_name: str = None,
                     end_condition: str = "blind", depth: float = 10.0,
                     direction_flip: bool = False,
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
        if not scope_body_ids:
            return self._error(
                "INVALID_PLAN", "scope_body_ids must contain at least one body id",
                stage="validate_plan", recoverable=True)

        doc, err = self.get_active_doc()
        if err:
            return err

        resolved_names = []
        resolved_before = []
        for body_id in scope_body_ids:
            body, record, resolve_err = self._find_body_by_identity(doc, body_id)
            if resolve_err:
                return resolve_err
            resolved_names.append(record["current_name"])
            resolved_before.append(record)

        if feature_name and feature_name in resolved_names:
            return self._error(
                "INVALID_PLAN",
                "Cut feature name must not collide with a semantic body name",
                stage="validate_plan", recoverable=True,
                details={"feature_name": feature_name,
                         "scope_body_ids": list(scope_body_ids),
                         "resolved_scope_bodies": resolved_names})

        result = self.advanced_cut(
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
            scope_bodies=resolved_names,
            normal_cut=normal_cut,
            optimize_geometry=optimize_geometry,
            feature_name=feature_name,
            auto_verify=auto_verify,
            auto_flags=auto_flags,
            expected_bbox=expected_bbox,
            expected_merge_bodies=expected_merge_bodies,
            unit=unit)
        if not result.get("success"):
            return result

        data = result.setdefault("data", {})
        resolved_after = []
        for body_id, before_record in zip(scope_body_ids, resolved_before):
            body, record, resolve_err = self._find_body_by_identity(doc, body_id)
            if resolve_err:
                rollback = self._rollback_semantic_feature(doc, result)
                message = (
                    f"Cut succeeded but semantic scope body '{body_id}' "
                    "was not stable after topology change")
                failure_data = dict(data)
                failure_data.update({
                    "semantic_identity_rollback": rollback,
                    "resolved_scope_before": resolved_before,
                    "identity_error": (resolve_err.get("data") or {}).get("error"),
                    "error": structured_error(
                        "INVARIANT_FAILED", message,
                        stage="validate_invariants", recoverable=True,
                        document_restored=rollback.get("feature_deleted"),
                        details={"body_id": body_id,
                                 "before": before_record,
                                 "rollback": rollback})})
                return self._result(
                    False, message, SwErrors.swFeatureError, failure_data)
            if record["current_name"] != record["canonical_name"]:
                rollback = self._rollback_semantic_feature(doc, result)
                message = (
                    f"Cut changed canonical body name for '{body_id}': "
                    f"{record['current_name']}")
                failure_data = dict(data)
                failure_data.update({
                    "semantic_identity_rollback": rollback,
                    "resolved_scope_before": resolved_before,
                    "resolved_scope_after_partial": resolved_after + [record],
                    "error": structured_error(
                        "INVARIANT_FAILED", message,
                        stage="validate_invariants", recoverable=True,
                        document_restored=rollback.get("feature_deleted"),
                        details={"body_id": body_id, "record": record,
                                 "rollback": rollback})})
                return self._result(
                    False, message, SwErrors.swFeatureError, failure_data)
            resolved_after.append(record)

        data["scope_body_ids"] = list(scope_body_ids)
        data["resolved_scope_bodies"] = resolved_names
        data["body_identities_before"] = resolved_before
        data["body_identities_after"] = resolved_after
        data["semantic_identity_verified"] = True
        data["semantic_naming"] = {
            "sketch_prefix": "S_", "feature_prefix": "F_", "body_prefix": "B_"}
        return result

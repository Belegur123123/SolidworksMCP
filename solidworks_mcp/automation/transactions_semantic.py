"""Transaction compatibility wrapper for semantic CAD identity operations."""

import sys

from .transactions import TransactionOperations as _BaseTransactionOperations


_SEMANTIC_IDENTITY_TOOLS = (
    "register_body_identity",
    "resolve_body_identity",
    "list_body_identities",
    "semantic_extrude",
    "semantic_cut",
)


class TransactionOperations(_BaseTransactionOperations):
    """Permit semantic body operations in bounded plans/transactions."""

    PLAN_OPERATIONS = set(_BaseTransactionOperations.PLAN_OPERATIONS) | set(
        _SEMANTIC_IDENTITY_TOOLS)

    def get_capabilities(self):
        """Report semantic identity support and both server registration layers.

        This deliberately piggybacks on the long-standing get_capabilities MCP
        tool.  Clients that cached an older tool manifest can therefore diagnose
        whether the running server already exposes the new semantic tools without
        using execute_python as an integration-test workaround.
        """
        result = super().get_capabilities()
        if not result.get("success"):
            return result

        from .. import tool_registry

        registered = {
            name: name in tool_registry.NEW_TOOL_NAMES
            for name in _SEMANTIC_IDENTITY_TOOLS
        }

        low_level_cache = None
        server_module = sys.modules.get("solidworks_mcp.server")
        low_level_server = getattr(server_module, "server", None)
        cache = getattr(low_level_server, "_tool_cache", None)
        if isinstance(cache, dict):
            low_level_cache = {
                name: name in cache for name in _SEMANTIC_IDENTITY_TOOLS
            }

        data = result.setdefault("data", {})
        data["semantic_body_identity"] = {
            "available": all(callable(getattr(self, name, None))
                             for name in _SEMANTIC_IDENTITY_TOOLS),
            "tools": list(_SEMANTIC_IDENTITY_TOOLS),
            "logical_id_prefix": "body:",
            "canonical_body_prefix": "B_",
            "feature_prefix": "F_",
            "sketch_prefix": "S_",
            "tool_registry_exposed": registered,
            "low_level_tool_cache_exposed": low_level_cache,
            "client_schema_refresh_required_after_toolset_change": True,
        }
        return result

    def _condition_matches(self, condition, steps):
        """Extend safe plan conditions with body_id_exists."""
        condition = dict(condition or {})
        allowed = {"step_success", "body_exists", "feature_exists",
                   "body_id_exists"}
        if set(condition) - allowed:
            raise ValueError("Unsafe/unknown plan condition")

        body_id = condition.pop("body_id_exists", None)
        if not super()._condition_matches(condition, steps):
            return False
        if body_id is None:
            return True

        doc, err = self.get_active_doc()
        if err:
            return False
        body, _, resolve_err = self._find_body_by_identity(doc, body_id)
        return body is not None and resolve_err is None

    def _validate_invariants(self, invariants, before, after, step_results):
        """Extend transaction invariants with required_body_ids."""
        invariants = dict(invariants or {})
        required_body_ids = list(invariants.pop("required_body_ids", []) or [])
        failures = list(super()._validate_invariants(
            invariants, before, after, step_results))
        if not required_body_ids:
            return failures

        doc, err = self.get_active_doc()
        if err:
            failures.append("active document unavailable for body-id validation")
            return failures
        for body_id in required_body_ids:
            body, record, resolve_err = self._find_body_by_identity(doc, body_id)
            if body is None or resolve_err is not None:
                failures.append(f"required body id '{body_id}'")
                continue
            if record.get("current_name") != record.get("canonical_name"):
                failures.append(
                    f"body id '{body_id}' is noncanonical: "
                    f"{record.get('current_name')}")
        return failures

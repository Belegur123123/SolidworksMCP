"""Transaction compatibility wrapper for semantic CAD identity operations."""

from .transactions import TransactionOperations as _BaseTransactionOperations


class TransactionOperations(_BaseTransactionOperations):
    """Permit semantic body operations in bounded plans/transactions."""

    PLAN_OPERATIONS = set(_BaseTransactionOperations.PLAN_OPERATIONS) | {
        "register_body_identity",
        "resolve_body_identity",
        "list_body_identities",
        "semantic_extrude",
        "semantic_cut",
    }

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

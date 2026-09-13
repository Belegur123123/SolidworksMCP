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

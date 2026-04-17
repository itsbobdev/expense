from __future__ import annotations

from app.models import Transaction


ALERT_KIND_CARD_FEE = "card_fee"
ALERT_KIND_HIGH_VALUE = "high_value"

ALERT_STATUS_PENDING = "pending"
ALERT_STATUS_UNRESOLVED = "unresolved"
ALERT_STATUS_RESOLVED = "resolved"
ACTIVE_ALERT_STATUSES = (ALERT_STATUS_PENDING, ALERT_STATUS_UNRESOLVED)

HIGH_VALUE_ALERT_THRESHOLD = 111.0


def classify_alert_kind(transaction: Transaction) -> str | None:
    """Return the alert kind for a transaction, if any."""
    if getattr(transaction, "is_reward", False):
        return None
    if getattr(transaction, "parent_transaction_id", None) is not None:
        return None

    categories = getattr(transaction, "categories", None) or []
    if "card_fees" in categories:
        return ALERT_KIND_CARD_FEE
    transaction_type = (getattr(transaction, "transaction_type", None) or "").lower()
    if transaction_type == "credit":
        return None
    if abs(float(getattr(transaction, "amount", 0.0) or 0.0)) > HIGH_VALUE_ALERT_THRESHOLD:
        return ALERT_KIND_HIGH_VALUE
    return None


def seed_import_alert_state(transaction: Transaction) -> None:
    """
    Seed alert fields before fee resolution and refund matching.

    Card-fee charges enter as pending.
    Card-fee refunds are tagged as card-fee alerts but let the resolver assign status.
    Non-fee high-value alerts are finalized later after refund matching.
    """
    alert_kind = classify_alert_kind(transaction)
    transaction.alert_kind = alert_kind

    if alert_kind is None:
        clear_alert_fields(transaction)
        return

    if alert_kind == ALERT_KIND_CARD_FEE:
        if transaction.is_refund:
            transaction.alert_status = None
            transaction.resolved_by_transaction_id = None
            transaction.resolved_method = None
            return
        if not transaction.alert_status:
            transaction.alert_status = ALERT_STATUS_PENDING
        return

    transaction.alert_status = None
    transaction.resolved_by_transaction_id = None
    transaction.resolved_method = None


def finalize_alert_state(transaction: Transaction) -> None:
    """
    Recompute the canonical alert fields after import/repair side effects complete.

    If the transaction still qualifies for the same alert kind, preserve manual
    resolved/unresolved state. Otherwise default active alerts back to pending.
    """
    previous_kind = getattr(transaction, "alert_kind", None)
    previous_status = getattr(transaction, "alert_status", None)
    next_kind = classify_alert_kind(transaction)

    if next_kind is None:
        clear_alert_fields(transaction)
        return

    preserve_manual_state = (
        previous_kind == next_kind
        and previous_status in {ALERT_STATUS_RESOLVED, ALERT_STATUS_UNRESOLVED}
    )

    transaction.alert_kind = next_kind

    if next_kind == ALERT_KIND_CARD_FEE:
        if preserve_manual_state:
            transaction.alert_status = previous_status
        else:
            transaction.alert_status = transaction.alert_status or ALERT_STATUS_PENDING
        if transaction.alert_status != ALERT_STATUS_RESOLVED:
            if transaction.resolved_method == "auto":
                transaction.resolved_method = None
            if transaction.is_refund:
                transaction.resolved_by_transaction_id = None
        return

    transaction.resolved_by_transaction_id = None
    if preserve_manual_state:
        transaction.alert_status = previous_status
    else:
        transaction.alert_status = ALERT_STATUS_PENDING
        transaction.resolved_method = None


def clear_alert_fields(transaction: Transaction) -> None:
    transaction.alert_kind = None
    transaction.alert_status = None
    transaction.resolved_by_transaction_id = None
    transaction.resolved_method = None


def get_alert_kind_label(alert_kind: str | None) -> str:
    if alert_kind == ALERT_KIND_CARD_FEE:
        return "CARD FEE"
    if alert_kind == ALERT_KIND_HIGH_VALUE:
        return "HIGH VALUE"
    return "ALERT"

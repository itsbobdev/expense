from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models import Bill, Transaction, TransactionSplit


ASSIGNMENT_METHOD_REFUND_LINKED_PENDING = "refund_linked_pending"


def collect_transaction_person_ids(transaction: Transaction) -> set[int]:
    person_ids = {split.person_id for split in transaction.transaction_splits}
    if transaction.assigned_to_person_id:
        person_ids.add(transaction.assigned_to_person_id)
    return person_ids


def delete_draft_bills_for_month(db: Session, billing_month: str | None, person_ids: set[int]) -> list[int]:
    if not billing_month or not person_ids:
        return []

    month_start = _month_start(billing_month)
    bills = (
        db.query(Bill)
        .filter(
            Bill.period_start == month_start,
            Bill.person_id.in_(person_ids),
            Bill.status == "draft",
        )
        .all()
    )
    deleted_bill_ids = [bill.id for bill in bills]
    for bill in bills:
        db.delete(bill)
    db.flush()
    return deleted_bill_ids


def sync_linked_refund_to_original(refund_transaction: Transaction, original_transaction: Transaction) -> None:
    refund_transaction.original_transaction_id = original_transaction.id
    refund_transaction.is_refund = True

    if original_transaction.needs_review:
        _mark_linked_refund_pending(refund_transaction)
        return

    provenance_method = _restore_provenance_method(refund_transaction)
    if provenance_method:
        refund_transaction.assignment_method = provenance_method

    if original_transaction.transaction_splits:
        refund_transaction.assigned_to_person_id = None
        refund_transaction.transaction_splits.clear()
        for split in sorted(original_transaction.transaction_splits, key=lambda item: item.sort_order):
            refund_transaction.transaction_splits.append(
                TransactionSplit(
                    person_id=split.person_id,
                    split_amount=-abs(split.split_amount),
                    split_percent=split.split_percent,
                    sort_order=split.sort_order,
                )
            )
    elif original_transaction.assigned_to_person_id:
        refund_transaction.transaction_splits.clear()
        refund_transaction.assigned_to_person_id = original_transaction.assigned_to_person_id
    else:
        _mark_linked_refund_pending(refund_transaction)
        return

    refund_transaction.assignment_confidence = _confidence_for_assignment_method(
        refund_transaction.assignment_method
    )
    refund_transaction.needs_review = False
    if refund_transaction.reviewed_at is None:
        refund_transaction.reviewed_at = _utcnow()


def sync_linked_refunds_for_original(
    db: Session,
    original_transaction: Transaction,
) -> dict[str, set[int]]:
    affected: dict[str, set[int]] = defaultdict(set)
    linked_refunds = (
        db.query(Transaction)
        .filter(Transaction.original_transaction_id == original_transaction.id)
        .all()
    )

    for refund_transaction in linked_refunds:
        _record_affected(affected, refund_transaction)
        sync_linked_refund_to_original(refund_transaction, original_transaction)
        _record_affected(affected, refund_transaction)

    db.flush()
    return {month: set(person_ids) for month, person_ids in affected.items()}


def _record_affected(affected: dict[str, set[int]], transaction: Transaction) -> None:
    if transaction.billing_month:
        affected.setdefault(transaction.billing_month, set()).update(
            collect_transaction_person_ids(transaction)
        )


def _mark_linked_refund_pending(refund_transaction: Transaction) -> None:
    if refund_transaction.assignment_method != ASSIGNMENT_METHOD_REFUND_LINKED_PENDING:
        refund_transaction.review_origin_method = refund_transaction.assignment_method or refund_transaction.review_origin_method
    refund_transaction.assigned_to_person_id = None
    refund_transaction.transaction_splits.clear()
    refund_transaction.assignment_confidence = None
    refund_transaction.assignment_method = ASSIGNMENT_METHOD_REFUND_LINKED_PENDING
    refund_transaction.needs_review = True
    refund_transaction.reviewed_at = None


def _restore_provenance_method(refund_transaction: Transaction) -> str | None:
    if refund_transaction.assignment_method == ASSIGNMENT_METHOD_REFUND_LINKED_PENDING:
        restored = refund_transaction.review_origin_method
        refund_transaction.review_origin_method = None
        return restored or "refund_auto_match"
    return refund_transaction.assignment_method


def _confidence_for_assignment_method(assignment_method: str | None) -> float | None:
    if assignment_method == "refund_manual_match":
        return 1.0
    if assignment_method == "refund_auto_match":
        return 0.95
    return None


def _month_start(billing_month: str) -> date:
    year, month = billing_month.split("-", 1)
    return date(int(year), int(month), 1)


def _utcnow():
    return datetime.utcnow()

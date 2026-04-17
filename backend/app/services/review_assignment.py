from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models import Bill, BillLineItem, Person, Transaction, TransactionSplit
from app.services.linked_refund_sync import (
    collect_transaction_person_ids as collect_linked_transaction_person_ids,
    delete_draft_bills_for_month,
    sync_linked_refunds_for_original,
)


@dataclass
class AssignmentOutcome:
    transaction: Transaction
    affected_draft_bill_ids: list[int]


def get_review_persons(db: Session) -> list[Person]:
    persons = (
        db.query(Person)
        .filter(Person.is_auto_created == False)
        .order_by(Person.name)
        .all()
    )
    self_person = db.query(Person).filter(Person.relationship_type == "self").first()
    if self_person:
        persons.append(self_person)
    return persons


def assign_transaction_to_person(
    db: Session,
    transaction: Transaction,
    person_id: int,
) -> AssignmentOutcome:
    affected_person_ids = _collect_transaction_person_ids(transaction) | {person_id}

    _ensure_review_origin_method(transaction)
    transaction.transaction_splits.clear()
    transaction.assigned_to_person_id = person_id
    transaction.assignment_confidence = 1.0
    transaction.assignment_method = "manual"
    transaction.needs_review = False
    transaction.reviewed_at = _utcnow()
    db.flush()

    affected_by_month = {transaction.billing_month: set(affected_person_ids)} if transaction.billing_month else {}
    _merge_affected_by_month(affected_by_month, sync_linked_refunds_for_original(db, transaction))
    deleted_bill_ids = _delete_draft_bills_for_months(db, affected_by_month)
    db.commit()
    db.refresh(transaction)
    return AssignmentOutcome(transaction=transaction, affected_draft_bill_ids=deleted_bill_ids)


def assign_transaction_equal_split(
    db: Session,
    transaction: Transaction,
    person_ids: list[int],
) -> AssignmentOutcome:
    _ensure_transaction_not_locked(db, transaction.id)
    if len(person_ids) < 2:
        raise ValueError("Select at least 2 people for a shared expense.")

    unique_person_ids = list(dict.fromkeys(person_ids))
    if len(unique_person_ids) < 2:
        raise ValueError("Select at least 2 different people for a shared expense.")

    affected_person_ids = _collect_transaction_person_ids(transaction) | set(unique_person_ids)
    _ensure_review_origin_method(transaction)

    transaction.assigned_to_person_id = None
    transaction.assignment_confidence = 1.0
    transaction.assignment_method = "shared_manual"
    transaction.needs_review = False
    transaction.reviewed_at = _utcnow()
    transaction.transaction_splits.clear()
    db.flush()

    for sort_order, split in enumerate(_build_equal_splits(transaction.amount, unique_person_ids)):
        transaction.transaction_splits.append(
            TransactionSplit(
                person_id=split.person_id,
                split_amount=split.amount,
                split_percent=split.percent,
                sort_order=sort_order,
            )
        )

    db.flush()
    affected_by_month = {transaction.billing_month: set(affected_person_ids)} if transaction.billing_month else {}
    _merge_affected_by_month(affected_by_month, sync_linked_refunds_for_original(db, transaction))
    deleted_bill_ids = _delete_draft_bills_for_months(db, affected_by_month)
    db.commit()
    db.refresh(transaction)
    return AssignmentOutcome(transaction=transaction, affected_draft_bill_ids=deleted_bill_ids)


def undo_review_assignment(db: Session, transaction: Transaction) -> AssignmentOutcome:
    _ensure_transaction_not_locked(db, transaction.id)

    affected_person_ids = _collect_transaction_person_ids(transaction)
    transaction.assigned_to_person_id = None
    transaction.assignment_confidence = None
    transaction.assignment_method = transaction.review_origin_method or transaction.assignment_method
    transaction.needs_review = True
    transaction.reviewed_at = None
    transaction.transaction_splits.clear()
    db.flush()

    affected_by_month = {transaction.billing_month: set(affected_person_ids)} if transaction.billing_month else {}
    _merge_affected_by_month(affected_by_month, sync_linked_refunds_for_original(db, transaction))
    deleted_bill_ids = _delete_draft_bills_for_months(db, affected_by_month)
    db.commit()
    db.refresh(transaction)
    return AssignmentOutcome(transaction=transaction, affected_draft_bill_ids=deleted_bill_ids)


def transaction_has_locked_bill(db: Session, transaction_id: int) -> bool:
    return (
        db.query(BillLineItem)
        .join(Bill, Bill.id == BillLineItem.bill_id)
        .filter(
            BillLineItem.transaction_id == transaction_id,
            Bill.status.in_(["finalized", "paid"]),
        )
        .first()
        is not None
    )


def split_summary(transaction: Transaction) -> list[tuple[str, float]]:
    return [
        (
            split.person.name if split.person else f"Person {split.person_id}",
            split.split_amount,
        )
        for split in transaction.transaction_splits
    ]


@dataclass
class _SplitAllocation:
    person_id: int
    amount: float
    percent: float


def _build_equal_splits(total_amount: float, person_ids: list[int]) -> list[_SplitAllocation]:
    sign = -1 if total_amount < 0 else 1
    total_cents = int(round(abs(total_amount) * 100))
    per_person_cents, remainder = divmod(total_cents, len(person_ids))
    allocations: list[_SplitAllocation] = []

    for index, person_id in enumerate(person_ids):
        cents = per_person_cents + (remainder if index == len(person_ids) - 1 else 0)
        amount = sign * (cents / 100)
        percent = round((cents / total_cents) * 100, 6) if total_cents else 0.0
        allocations.append(_SplitAllocation(person_id=person_id, amount=amount, percent=percent))

    return allocations


def _ensure_review_origin_method(transaction: Transaction) -> None:
    if not transaction.review_origin_method:
        transaction.review_origin_method = transaction.assignment_method


def _collect_transaction_person_ids(transaction: Transaction) -> set[int]:
    return collect_linked_transaction_person_ids(transaction)


def _delete_draft_bills_for_months(db: Session, affected_by_month: dict[str | None, set[int]]) -> list[int]:
    deleted_bill_ids: set[int] = set()
    for billing_month, person_ids in affected_by_month.items():
        deleted_bill_ids.update(delete_draft_bills_for_month(db, billing_month, person_ids))
    return sorted(deleted_bill_ids)


def _merge_affected_by_month(
    target: dict[str | None, set[int]],
    source: dict[str, set[int]],
) -> None:
    for billing_month, person_ids in source.items():
        target.setdefault(billing_month, set()).update(person_ids)


def _ensure_transaction_not_locked(db: Session, transaction_id: int) -> None:
    if transaction_has_locked_bill(db, transaction_id):
        raise ValueError("This transaction is already included in a finalized or paid bill.")


def _month_start(billing_month: str) -> date:
    year, month = billing_month.split("-", 1)
    return date(int(year), int(month), 1)


def _utcnow():
    return datetime.utcnow()

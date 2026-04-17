from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Bill, Statement, Transaction
from app.services.alert_policy import finalize_alert_state
from app.services.categorizer import TransactionCategorizer


def is_account_statement_data(data: dict) -> bool:
    return bool(data.get("account_number_last_4") or data.get("account_name"))


def normalize_statement_amount(raw_amount: float, is_account_statement: bool) -> float:
    return -raw_amount if is_account_statement else raw_amount


def load_statement_source_data(statement: Statement) -> dict | None:
    if not statement.raw_file_path:
        return None

    for json_path in _candidate_statement_paths(statement.raw_file_path):
        if not json_path.exists():
            continue
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return None


@dataclass
class AccountStatementRepairResult:
    repaired_statements: int
    repaired_transactions: int
    repaired_splits: int
    deleted_draft_bill_ids: list[int]
    skipped_statements: list[int]


def repair_account_statement_history(db: Session) -> AccountStatementRepairResult:
    categorizer = TransactionCategorizer(db)
    repaired_statements = 0
    repaired_transactions = 0
    repaired_splits = 0
    deleted_draft_bill_ids: set[int] = set()
    skipped_statements: list[int] = []

    statements = db.query(Statement).order_by(Statement.id).all()
    for statement in statements:
        source_data = load_statement_source_data(statement)
        if not source_data or not is_account_statement_data(source_data):
            continue

        source_transactions = source_data.get("transactions", [])
        db_transactions = list(statement.transactions)
        if len(source_transactions) != len(db_transactions):
            skipped_statements.append(statement.id)
            continue

        repaired_statements += 1
        affected_person_ids: set[int] = set()

        for txn, source_txn in zip(db_transactions, source_transactions):
            affected_person_ids.update(_collect_affected_person_ids(txn))

            normalized_amount = normalize_statement_amount(source_txn.get("amount", 0.0), True)
            if txn.amount != normalized_amount:
                txn.amount = normalized_amount
                repaired_transactions += 1

            source_transaction_type = source_txn.get("transaction_type") or None
            if txn.transaction_type != source_transaction_type:
                txn.transaction_type = source_transaction_type
                repaired_transactions += 1

            txn.is_refund = False
            txn.original_transaction_id = None
            txn.review_origin_method = txn.review_origin_method if txn.assignment_method in {"manual", "shared_manual"} else None

            if txn.transaction_splits:
                _recalculate_split_amounts(txn)
                repaired_splits += len(txn.transaction_splits)

            if txn.is_reward:
                txn.needs_review = False
                txn.blacklist_category_id = None
                finalize_alert_state(txn)
                continue

            if txn.assignment_method in {"manual", "shared_manual"}:
                txn.needs_review = False
                finalize_alert_state(txn)
                continue

            result = categorizer.categorize(txn)
            txn.assigned_to_person_id = result.person_id
            txn.assignment_confidence = result.confidence
            txn.assignment_method = result.method
            txn.review_origin_method = result.method if result.needs_review else None
            txn.needs_review = result.needs_review
            txn.blacklist_category_id = result.blacklist_category_id
            finalize_alert_state(txn)

            affected_person_ids.update(_collect_affected_person_ids(txn))

        deleted_draft_bill_ids.update(
            _delete_draft_bills_for_month(db, statement.billing_month, affected_person_ids)
        )

    db.commit()
    return AccountStatementRepairResult(
        repaired_statements=repaired_statements,
        repaired_transactions=repaired_transactions,
        repaired_splits=repaired_splits,
        deleted_draft_bill_ids=sorted(deleted_draft_bill_ids),
        skipped_statements=skipped_statements,
    )


def _collect_affected_person_ids(transaction: Transaction) -> set[int]:
    person_ids = {split.person_id for split in transaction.transaction_splits}
    if transaction.assigned_to_person_id:
        person_ids.add(transaction.assigned_to_person_id)
    return person_ids


def _recalculate_split_amounts(transaction: Transaction) -> None:
    splits = sorted(transaction.transaction_splits, key=lambda split: split.sort_order)
    if not splits:
        return

    total_cents = int(round(abs(transaction.amount) * 100))
    sign = -1 if transaction.amount < 0 else 1

    if all(split.split_percent is not None for split in splits):
        remaining = total_cents
        for index, split in enumerate(splits):
            if index == len(splits) - 1:
                cents = remaining
            else:
                cents = int(round(total_cents * (split.split_percent / 100)))
                remaining -= cents
            split.split_amount = sign * (cents / 100)
        return

    per_split_cents, remainder = divmod(total_cents, len(splits))
    for index, split in enumerate(splits):
        cents = per_split_cents + (remainder if index == len(splits) - 1 else 0)
        split.split_amount = sign * (cents / 100)
        split.split_percent = round((cents / total_cents) * 100, 6) if total_cents else 0.0


def _delete_draft_bills_for_month(db: Session, billing_month: str | None, person_ids: set[int]) -> list[int]:
    if not billing_month or not person_ids:
        return []

    year, month = billing_month.split("-", 1)
    month_start = date(int(year), int(month), 1)
    bills = (
        db.query(Bill)
        .filter(
            Bill.period_start == month_start,
            Bill.person_id.in_(person_ids),
            Bill.status == "draft",
        )
        .all()
    )
    deleted_ids = [bill.id for bill in bills]
    for bill in bills:
        db.delete(bill)
    db.flush()
    return deleted_ids


def _candidate_statement_paths(raw_file_path: str) -> list[Path]:
    raw_path = Path(raw_file_path)
    backend_dir = Path(__file__).resolve().parents[2]
    repo_root = Path(__file__).resolve().parents[3]

    candidates = [raw_path]
    if not raw_path.is_absolute():
        candidates.append(backend_dir / raw_path)
        candidates.append(repo_root / raw_path)

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models import Bill, BillLineItem, ManualBill, Person, Transaction, TransactionSplit


LIVE_STATE_VERSION = 1


def export_live_state(db: Session, output_path: Path) -> dict[str, int]:
    transaction_key_map, transaction_entries = build_transaction_entries(db)
    manual_bill_key_map, manual_bill_entries = build_manual_bill_entries(db)
    bill_entries = build_bill_entries(db, transaction_key_map, manual_bill_key_map)

    payload = {
        "version": LIVE_STATE_VERSION,
        "generated_at": datetime.utcnow().isoformat(),
        "transactions": transaction_entries,
        "manual_bills": manual_bill_entries,
        "bills": bill_entries,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "transactions": len(transaction_entries),
        "manual_bills": len(manual_bill_entries),
        "bills": len(bill_entries),
    }


def import_live_state(db: Session, input_path: Path) -> dict[str, int]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    version = payload.get("version")
    if version != LIVE_STATE_VERSION:
        raise ValueError(f"Unsupported live-state version: {version}")

    people_by_name = {person.name: person for person in db.query(Person).all()}

    transaction_by_key, _ = build_transaction_lookup(db)
    manual_bill_by_key = build_manual_bill_lookup(db)

    imported_transactions = _import_transactions(db, payload.get("transactions", []), transaction_by_key, people_by_name)
    imported_manual_bills, manual_bill_by_key = _import_manual_bills(
        db,
        payload.get("manual_bills", []),
        manual_bill_by_key,
        people_by_name,
    )
    imported_bills = _import_bills(
        db,
        payload.get("bills", []),
        transaction_by_key,
        manual_bill_by_key,
        people_by_name,
    )

    db.commit()
    return {
        "transactions": imported_transactions,
        "manual_bills": imported_manual_bills,
        "bills": imported_bills,
    }


def build_transaction_entries(db: Session) -> tuple[dict[int, str], list[dict[str, Any]]]:
    transactions = _load_transactions(db)
    transaction_key_map, _ = _build_transaction_key_map(transactions)
    entries: list[dict[str, Any]] = []

    for transaction in transactions:
        identity = _transaction_identity(transaction)
        entry = {
            "transaction_key": transaction_key_map[transaction.id],
            "statement_raw_file_path": identity["statement_raw_file_path"],
            "occurrence_index": _occurrence_index_for_transaction(transaction, transaction_key_map),
            "identity": {
                "transaction_date": identity["transaction_date"],
                "merchant_name": identity["merchant_name"],
                "amount": identity["amount"],
                "is_refund": identity["is_refund"] == "1",
            },
            "assigned_to_person": transaction.assigned_person.name if transaction.assigned_person else None,
            "assignment_method": transaction.assignment_method,
            "assignment_confidence": transaction.assignment_confidence,
            "needs_review": bool(transaction.needs_review),
            "reviewed_at": _format_datetime(transaction.reviewed_at),
            "review_origin_method": transaction.review_origin_method,
            "alert_status": transaction.alert_status,
            "alert_kind": transaction.alert_kind,
            "resolved_method": transaction.resolved_method,
            "resolved_by_transaction_key": transaction_key_map.get(transaction.resolved_by_transaction_id),
            "original_transaction_key": transaction_key_map.get(transaction.original_transaction_id),
            "splits": [
                {
                    "person_name": split.person.name if split.person else None,
                    "split_amount": split.split_amount,
                    "split_percent": split.split_percent,
                    "sort_order": split.sort_order,
                }
                for split in sorted(transaction.transaction_splits, key=lambda item: item.sort_order)
            ],
        }
        entries.append(entry)

    entries.sort(key=lambda item: item["transaction_key"])
    return transaction_key_map, entries


def build_transaction_lookup(db: Session) -> tuple[dict[str, Transaction], dict[int, str]]:
    transactions = _load_transactions(db)
    transaction_key_map, _ = _build_transaction_key_map(transactions)
    by_key = {transaction_key_map[txn.id]: txn for txn in transactions}
    return by_key, transaction_key_map


def build_manual_bill_entries(db: Session) -> tuple[dict[int, str], list[dict[str, Any]]]:
    manual_bills = (
        db.query(ManualBill)
        .options(joinedload(ManualBill.person))
        .order_by(ManualBill.created_at, ManualBill.id)
        .all()
    )
    key_map = {manual_bill.id: manual_bill_key(manual_bill) for manual_bill in manual_bills}
    entries = [
        {
            "manual_bill_key": key_map[manual_bill.id],
            "person_name": manual_bill.person.name if manual_bill.person else None,
            "billing_month": manual_bill.billing_month,
            "description": manual_bill.description,
            "amount": manual_bill.amount,
            "manual_type": manual_bill.manual_type,
            "created_at": _format_datetime(manual_bill.created_at),
        }
        for manual_bill in manual_bills
    ]
    entries.sort(key=lambda item: item["manual_bill_key"])
    return key_map, entries


def build_manual_bill_lookup(db: Session) -> dict[str, ManualBill]:
    manual_bills = (
        db.query(ManualBill)
        .options(joinedload(ManualBill.person))
        .order_by(ManualBill.created_at, ManualBill.id)
        .all()
    )
    return {manual_bill_key(manual_bill): manual_bill for manual_bill in manual_bills}


def build_bill_entries(
    db: Session,
    transaction_key_map: dict[int, str],
    manual_bill_key_map: dict[int, str],
) -> list[dict[str, Any]]:
    bills = (
        db.query(Bill)
        .options(
            joinedload(Bill.person),
            joinedload(Bill.line_items).joinedload(BillLineItem.transaction),
            joinedload(Bill.line_items).joinedload(BillLineItem.manual_bill),
        )
        .order_by(Bill.created_at, Bill.id)
        .all()
    )

    entries: list[dict[str, Any]] = []
    for bill in bills:
        entries.append(
            {
                "bill_key": bill_key(bill),
                "person_name": bill.person.name if bill.person else None,
                "period_start": bill.period_start.isoformat(),
                "period_end": bill.period_end.isoformat(),
                "total_amount": bill.total_amount,
                "status": bill.status,
                "created_at": _format_datetime(bill.created_at),
                "finalized_at": _format_datetime(bill.finalized_at),
                "paid_at": _format_datetime(bill.paid_at),
                "line_items": [
                    {
                        "amount": line_item.amount,
                        "description": line_item.description,
                        "transaction_key": transaction_key_map.get(line_item.transaction_id),
                        "manual_bill_key": manual_bill_key_map.get(line_item.manual_bill_id),
                    }
                    for line_item in sorted(bill.line_items, key=lambda item: item.id)
                ],
            }
        )

    entries.sort(key=lambda item: item["bill_key"])
    return entries


def statement_path_suffix(path_value: str | Path | None) -> str:
    if not path_value:
        return ""
    normalized_parts = [part for part in str(path_value).replace("\\", "/").split("/") if part and part != "."]
    lowered = [part.casefold() for part in normalized_parts]
    if "statements" in lowered:
        index = lowered.index("statements")
        return "/".join(normalized_parts[index:])
    return Path(str(path_value)).name


def manual_bill_key(manual_bill: ManualBill) -> str:
    identity = {
        "person_name": manual_bill.person.name if manual_bill.person else None,
        "billing_month": manual_bill.billing_month,
        "description": manual_bill.description,
        "amount": _format_decimal(manual_bill.amount),
        "manual_type": manual_bill.manual_type,
        "created_at": _format_datetime(manual_bill.created_at),
    }
    return f"manual::{_stable_hash(identity)}"


def bill_key(bill: Bill) -> str:
    identity = {
        "person_name": bill.person.name if bill.person else None,
        "period_start": bill.period_start.isoformat(),
        "period_end": bill.period_end.isoformat(),
        "created_at": _format_datetime(bill.created_at),
    }
    return f"bill::{_stable_hash(identity)}"


def _import_transactions(
    db: Session,
    entries: list[dict[str, Any]],
    transaction_by_key: dict[str, Transaction],
    people_by_name: dict[str, Any],
) -> int:
    pending_transaction_links: list[tuple[Transaction, str | None, str | None]] = []
    count = 0

    for entry in entries:
        transaction = transaction_by_key.get(entry["transaction_key"])
        if transaction is None:
            raise ValueError(f"Transaction not found for key: {entry['transaction_key']}")

        person_name = entry.get("assigned_to_person")
        if person_name and person_name not in people_by_name:
            raise ValueError(f"Unknown assigned person: {person_name}")
        transaction.assigned_to_person_id = people_by_name[person_name].id if person_name else None
        transaction.assignment_method = entry.get("assignment_method")
        transaction.assignment_confidence = entry.get("assignment_confidence")
        transaction.needs_review = bool(entry.get("needs_review"))
        transaction.reviewed_at = _parse_datetime(entry.get("reviewed_at"))
        transaction.review_origin_method = entry.get("review_origin_method")
        transaction.alert_status = entry.get("alert_status")
        transaction.alert_kind = entry.get("alert_kind")
        transaction.resolved_method = entry.get("resolved_method")

        transaction.transaction_splits.clear()
        db.flush()
        for split in entry.get("splits", []):
            split_person_name = split.get("person_name")
            if split_person_name not in people_by_name:
                raise ValueError(f"Unknown split person: {split_person_name}")
            transaction.transaction_splits.append(
                TransactionSplit(
                    person_id=people_by_name[split_person_name].id,
                    split_amount=split["split_amount"],
                    split_percent=split.get("split_percent"),
                    sort_order=split.get("sort_order", 0),
                )
            )

        pending_transaction_links.append(
            (
                transaction,
                entry.get("original_transaction_key"),
                entry.get("resolved_by_transaction_key"),
            )
        )
        count += 1

    db.flush()

    for transaction, original_key, resolved_key in pending_transaction_links:
        if original_key and original_key not in transaction_by_key:
            raise ValueError(f"Referenced original transaction not found: {original_key}")
        if resolved_key and resolved_key not in transaction_by_key:
            raise ValueError(f"Referenced resolved-by transaction not found: {resolved_key}")
        transaction.original_transaction_id = transaction_by_key[original_key].id if original_key else None
        transaction.resolved_by_transaction_id = transaction_by_key[resolved_key].id if resolved_key else None

    db.flush()
    return count


def _import_manual_bills(
    db: Session,
    entries: list[dict[str, Any]],
    manual_bill_by_key: dict[str, ManualBill],
    people_by_name: dict[str, Any],
) -> tuple[int, dict[str, ManualBill]]:
    count = 0

    for entry in entries:
        person_name = entry.get("person_name")
        if person_name not in people_by_name:
            raise ValueError(f"Unknown manual bill person: {person_name}")

        manual_bill = manual_bill_by_key.get(entry["manual_bill_key"])
        if manual_bill is None:
            manual_bill = ManualBill()
            db.add(manual_bill)

        manual_bill.person_id = people_by_name[person_name].id
        manual_bill.billing_month = entry["billing_month"]
        manual_bill.description = entry["description"]
        manual_bill.amount = entry["amount"]
        manual_bill.manual_type = entry["manual_type"]
        manual_bill.created_at = _parse_datetime(entry["created_at"])

        db.flush()
        manual_bill_by_key[entry["manual_bill_key"]] = manual_bill
        count += 1

    return count, manual_bill_by_key


def _import_bills(
    db: Session,
    entries: list[dict[str, Any]],
    transaction_by_key: dict[str, Transaction],
    manual_bill_by_key: dict[str, ManualBill],
    people_by_name: dict[str, Any],
) -> int:
    existing_bills = (
        db.query(Bill)
        .options(joinedload(Bill.person), joinedload(Bill.line_items))
        .order_by(Bill.created_at, Bill.id)
        .all()
    )
    bill_by_key = {bill_key(bill): bill for bill in existing_bills}
    count = 0

    for entry in entries:
        person_name = entry.get("person_name")
        if person_name not in people_by_name:
            raise ValueError(f"Unknown bill person: {person_name}")

        bill = bill_by_key.get(entry["bill_key"])
        if bill is None:
            bill = Bill()
            db.add(bill)

        bill.person_id = people_by_name[person_name].id
        bill.period_start = datetime.fromisoformat(entry["period_start"]).date()
        bill.period_end = datetime.fromisoformat(entry["period_end"]).date()
        bill.total_amount = entry["total_amount"]
        bill.status = entry["status"]
        bill.created_at = _parse_datetime(entry["created_at"])
        bill.finalized_at = _parse_datetime(entry.get("finalized_at"))
        bill.paid_at = _parse_datetime(entry.get("paid_at"))

        bill.line_items.clear()
        db.flush()
        for line_item in entry.get("line_items", []):
            transaction_key = line_item.get("transaction_key")
            manual_bill_key_value = line_item.get("manual_bill_key")
            if transaction_key and transaction_key not in transaction_by_key:
                raise ValueError(f"Referenced bill transaction not found: {transaction_key}")
            if manual_bill_key_value and manual_bill_key_value not in manual_bill_by_key:
                raise ValueError(f"Referenced bill manual bill not found: {manual_bill_key_value}")
            bill.line_items.append(
                BillLineItem(
                    transaction_id=transaction_by_key[transaction_key].id if transaction_key else None,
                    manual_bill_id=manual_bill_by_key[manual_bill_key_value].id if manual_bill_key_value else None,
                    amount=line_item["amount"],
                    description=line_item.get("description"),
                )
            )

        db.flush()
        bill_by_key[entry["bill_key"]] = bill
        count += 1

    return count


def _load_transactions(db: Session) -> list[Transaction]:
    return (
        db.query(Transaction)
        .options(
            joinedload(Transaction.statement),
            joinedload(Transaction.assigned_person),
            joinedload(Transaction.transaction_splits).joinedload(TransactionSplit.person),
        )
        .order_by(Transaction.statement_id, Transaction.id)
        .all()
    )


def _build_transaction_key_map(
    transactions: list[Transaction],
) -> tuple[dict[int, str], dict[int, int]]:
    seen: dict[tuple[str, str, str, str, str], int] = defaultdict(int)
    transaction_key_map: dict[int, str] = {}
    occurrence_map: dict[int, int] = {}

    for transaction in transactions:
        identity = _transaction_identity(transaction)
        identity_tuple = tuple(identity.values())
        occurrence_index = seen[identity_tuple]
        seen[identity_tuple] += 1
        occurrence_map[transaction.id] = occurrence_index
        transaction_key_map[transaction.id] = transaction_key(identity, occurrence_index)

    return transaction_key_map, occurrence_map


def _occurrence_index_for_transaction(transaction: Transaction, transaction_key_map: dict[int, str]) -> int:
    key = transaction_key_map[transaction.id]
    return int(key.rsplit("#", 1)[1])


def _transaction_identity(transaction: Transaction) -> dict[str, str]:
    statement_path = statement_path_suffix(transaction.statement.raw_file_path if transaction.statement else None)
    return {
        "statement_raw_file_path": statement_path,
        "transaction_date": transaction.transaction_date.isoformat(),
        "merchant_name": transaction.merchant_name or "",
        "amount": _format_decimal(abs(transaction.amount)),
        "is_refund": "1" if transaction.is_refund else "0",
    }


def transaction_key(identity: dict[str, str], occurrence_index: int) -> str:
    digest = _stable_hash(identity)
    return f"{identity['statement_raw_file_path']}#{digest}#{occurrence_index}"


def _format_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _format_decimal(value: float | Decimal | None) -> str:
    if value is None:
        return ""
    decimal_value = Decimal(str(value))
    normalized = format(decimal_value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _stable_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()[:16]

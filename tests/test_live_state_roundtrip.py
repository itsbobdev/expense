from datetime import date, datetime
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import Bill, BillLineItem, ManualBill, Person, Statement, Transaction, TransactionSplit
from live_state import export_live_state, import_live_state


def _build_session():
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal


def _seed_people(db):
    alice = Person(name="Alice", relationship_type="parent", card_last_4_digits=["1234"], is_auto_created=False)
    bob = Person(name="Bob", relationship_type="spouse", card_last_4_digits=["5678"], is_auto_created=False)
    self_person = Person(name="Self", relationship_type="self", card_last_4_digits=[], is_auto_created=True)
    db.add_all([alice, bob, self_person])
    db.commit()
    return alice, bob, self_person


def _seed_statement(db):
    statement = Statement(
        filename="sample.json",
        bank_name="UOB",
        card_last_4="1234",
        statement_date=date(2026, 3, 31),
        billing_month="2026-03",
        raw_file_path="..\\statements\\2026\\03\\uob\\sample.json",
    )
    db.add(statement)
    db.commit()
    return statement


def _seed_transactions(db, statement, *, enriched: bool):
    dinner_one = Transaction(
        statement_id=statement.id,
        billing_month="2026-03",
        transaction_date=date(2026, 3, 15),
        merchant_name="DINNER",
        raw_description="DINNER",
        amount=40.0,
        is_refund=False,
        needs_review=not enriched,
        assignment_method="manual" if enriched else "category_review",
        review_origin_method="category_review" if enriched else None,
        reviewed_at=datetime(2026, 4, 1, 10, 0, 0) if enriched else None,
    )
    dinner_two = Transaction(
        statement_id=statement.id,
        billing_month="2026-03",
        transaction_date=date(2026, 3, 15),
        merchant_name="DINNER",
        raw_description="DINNER",
        amount=40.0,
        is_refund=False,
        needs_review=not enriched,
        assignment_method="shared_manual" if enriched else "category_review",
        review_origin_method="category_review" if enriched else None,
        reviewed_at=datetime(2026, 4, 1, 10, 5, 0) if enriched else None,
    )
    fee = Transaction(
        statement_id=statement.id,
        billing_month="2026-03",
        transaction_date=date(2026, 3, 20),
        merchant_name="ANNUAL FEE",
        raw_description="ANNUAL FEE",
        amount=100.0,
        alert_kind="card_fee" if enriched else None,
        alert_status="resolved" if enriched else "pending",
        resolved_method="auto" if enriched else None,
        needs_review=False,
    )
    reversal = Transaction(
        statement_id=statement.id,
        billing_month="2026-03",
        transaction_date=date(2026, 3, 21),
        merchant_name="ANNUAL FEE REVERSAL",
        raw_description="ANNUAL FEE REVERSAL",
        amount=-100.0,
        is_refund=True,
        assignment_method="refund_manual_match" if enriched else None,
        review_origin_method="refund_orphan" if enriched else None,
        reviewed_at=datetime(2026, 4, 1, 11, 0, 0) if enriched else None,
        alert_kind="card_fee" if enriched else None,
        alert_status="resolved" if enriched else None,
        resolved_method="auto" if enriched else None,
        needs_review=False,
    )
    db.add_all([dinner_one, dinner_two, fee, reversal])
    db.commit()

    if enriched:
        alice = db.query(Person).filter(Person.name == "Alice").one()
        bob = db.query(Person).filter(Person.name == "Bob").one()
        dinner_one.assigned_to_person_id = alice.id
        dinner_one.assignment_confidence = 1.0
        dinner_one.needs_review = False

        dinner_two.transaction_splits.append(
            TransactionSplit(
                person_id=alice.id,
                split_amount=20.0,
                split_percent=50.0,
                sort_order=0,
            )
        )
        dinner_two.transaction_splits.append(
            TransactionSplit(
                person_id=bob.id,
                split_amount=20.0,
                split_percent=50.0,
                sort_order=1,
            )
        )
        reversal.original_transaction_id = dinner_one.id
        fee.resolved_by_transaction_id = reversal.id
        db.commit()

    return dinner_one, dinner_two, fee, reversal


def _seed_manual_and_bill(db, transaction, *, enriched: bool):
    alice = db.query(Person).filter(Person.name == "Alice").one()
    manual_bill = None
    if enriched:
        manual_bill = ManualBill(
            person_id=alice.id,
            amount=12.34,
            description="Taxi adjustment",
            billing_month="2026-03",
            manual_type=ManualBill.TYPE_MANUALLY_ADDED,
            created_at=datetime(2026, 4, 2, 9, 0, 0),
        )
        db.add(manual_bill)
        db.flush()

        bill = Bill(
            person_id=alice.id,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1),
            total_amount=52.34,
            status="finalized",
            created_at=datetime(2026, 4, 2, 12, 0, 0),
            finalized_at=datetime(2026, 4, 2, 12, 30, 0),
        )
        db.add(bill)
        db.flush()
        db.add_all(
            [
                BillLineItem(
                    bill_id=bill.id,
                    transaction_id=transaction.id,
                    amount=40.0,
                    description="DINNER",
                ),
                BillLineItem(
                    bill_id=bill.id,
                    manual_bill_id=manual_bill.id,
                    amount=12.34,
                    description="Taxi adjustment",
                ),
            ]
        )
        db.commit()


def test_live_state_roundtrip_restores_duplicate_transaction_state(tmp_path):
    source_session = _build_session()
    destination_session = _build_session()
    snapshot_path = tmp_path / "live_state.json"

    with source_session() as db:
        _seed_people(db)
        statement = _seed_statement(db)
        dinner_one, dinner_two, fee, reversal = _seed_transactions(db, statement, enriched=True)
        _seed_manual_and_bill(db, dinner_one, enriched=True)
        export_live_state(db, snapshot_path)

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert len(payload["transactions"]) == 4
    dinner_entries = [
        entry
        for entry in payload["transactions"]
        if entry["identity"]["merchant_name"] == "DINNER"
    ]
    assert sorted(entry["occurrence_index"] for entry in dinner_entries) == [0, 1]

    with destination_session() as db:
        _seed_people(db)
        statement = _seed_statement(db)
        _seed_transactions(db, statement, enriched=False)
        result = import_live_state(db, snapshot_path)
        assert result == {"transactions": 4, "manual_bills": 1, "bills": 1}

        dinner_transactions = (
            db.query(Transaction)
            .filter(Transaction.merchant_name == "DINNER")
            .order_by(Transaction.id)
            .all()
        )
        assert dinner_transactions[0].assignment_method == "manual"
        assert dinner_transactions[0].assigned_person.name == "Alice"
        assert dinner_transactions[0].needs_review is False
        assert dinner_transactions[1].assignment_method == "shared_manual"
        assert [split.person.name for split in dinner_transactions[1].transaction_splits] == ["Alice", "Bob"]

        fee = db.query(Transaction).filter(Transaction.merchant_name == "ANNUAL FEE").one()
        reversal = db.query(Transaction).filter(Transaction.merchant_name == "ANNUAL FEE REVERSAL").one()
        assert fee.resolved_by_transaction_id == reversal.id
        assert reversal.original_transaction_id == dinner_transactions[0].id

        manual_bills = db.query(ManualBill).all()
        assert len(manual_bills) == 1
        assert manual_bills[0].description == "Taxi adjustment"

        bills = db.query(Bill).all()
        assert len(bills) == 1
        assert bills[0].status == "finalized"
        assert len(bills[0].line_items) == 2

        # Idempotent re-import
        import_live_state(db, snapshot_path)
        assert db.query(ManualBill).count() == 1
        assert db.query(Bill).count() == 1

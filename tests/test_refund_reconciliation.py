import json
import sys
from pathlib import Path
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import AssignmentRule, Person, Statement, Transaction
from app.services.importer import StatementImporter
from app.services.refund_handler import RefundHandler


def create_person_with_card(db, *, name: str, relationship_type: str, card_last_4: str):
    person = Person(
        name=name,
        relationship_type=relationship_type,
        card_last_4_digits=[card_last_4],
        is_auto_created=False,
    )
    db.add(person)
    db.flush()
    db.add(
        AssignmentRule(
            priority=100,
            rule_type="card_direct",
            conditions={"card_last_4": card_last_4},
            assign_to_person_id=person.id,
            is_active=True,
        )
    )
    db.commit()
    return person


def test_importing_original_later_reconciles_older_orphan_refund(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    refund_json = tmp_path / "refund.json"
    refund_json.write_text(
        json.dumps(
            {
                "filename": "refund.json",
                "bank_name": "UOB",
                "card_last_4": "7857",
                "statement_date": "2025-12-31",
                "transactions": [
                    {
                        "transaction_date": "2025-12-02",
                        "merchant_name": "ALLIANZ INSURANCE SING",
                        "amount": -98.10,
                        "is_refund": True,
                        "categories": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    original_json = tmp_path / "original.json"
    original_json.write_text(
        json.dumps(
            {
                "filename": "original.json",
                "bank_name": "UOB",
                "card_last_4": "7857",
                "statement_date": "2025-11-30",
                "transactions": [
                    {
                        "transaction_date": "2025-11-22",
                        "merchant_name": "ALLIANZ INSURANCE SING",
                        "amount": 98.10,
                        "is_refund": False,
                        "categories": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with SessionLocal() as db:
        importer = StatementImporter(db)

        refund_result = importer.import_file(refund_json, "2026-01")
        assert refund_result.refunds_auto_matched == 0

        refund = db.query(Transaction).filter(Transaction.amount == -98.10).one()
        assert refund.assignment_method == "refund_orphan"
        assert refund.needs_review is True
        assert refund.original_transaction_id is None

        original_result = importer.import_file(original_json, "2025-12")
        assert original_result.refunds_auto_matched == 1

        refund = db.query(Transaction).filter(Transaction.amount == -98.10).one()
        original = db.query(Transaction).filter(Transaction.amount == 98.10).one()

        assert refund.assignment_method == "refund_auto_match"
        assert refund.needs_review is False
        assert refund.original_transaction_id == original.id
        assert refund.assigned_to_person_id == original.assigned_to_person_id

        assert db.query(Statement).count() == 2
        assert db.query(Transaction).count() == 2


def test_matching_refund_after_original_assignment_uses_current_owner():
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        owner = create_person_with_card(db, name="foo_wah_liang", relationship_type="parent", card_last_4="4474")
        statement = Statement(
            filename="uob.json",
            bank_name="UOB",
            card_last_4="4474",
            statement_date=date(2025, 12, 31),
            billing_month="2025-12",
            raw_file_path="uob.json",
        )
        db.add(statement)
        db.flush()

        original = Transaction(
            statement_id=statement.id,
            billing_month="2025-12",
            transaction_date=date(2025, 12, 3),
            merchant_name="BIG HOTEL",
            amount=200.0,
            assigned_to_person_id=owner.id,
            assignment_method="manual",
            needs_review=False,
        )
        refund = Transaction(
            statement_id=statement.id,
            billing_month="2025-12",
            transaction_date=date(2025, 12, 10),
            merchant_name="BIG HOTEL",
            amount=-200.0,
            is_refund=True,
        )
        db.add_all([original, refund])
        db.commit()

        matched = RefundHandler(db).process_refund(refund)
        db.refresh(refund)

        assert matched is True
        assert refund.original_transaction_id == original.id
        assert refund.assigned_to_person_id == owner.id
        assert refund.assignment_method == "refund_auto_match"
        assert refund.needs_review is False

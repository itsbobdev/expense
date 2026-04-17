import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import AssignmentRule, Person, Transaction
from app.services.importer import StatementImporter


def make_session_local():
    engine = create_engine("sqlite:///:memory:")
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_local


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def seed_card_owner(db, *, person_name: str, relationship_type: str, card_last_4: str):
    person = Person(
        name=person_name,
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


def test_large_non_fee_charge_creates_high_value_alert(tmp_path):
    session_local = make_session_local()
    json_path = tmp_path / "charge.json"
    write_json(
        json_path,
        {
            "filename": "charge.json",
            "bank_name": "UOB",
            "card_last_4": "7857",
            "statement_date": "2025-12-31",
            "transactions": [
                {
                    "transaction_date": "2025-12-02",
                    "merchant_name": "BIG HOTEL",
                    "amount": 200.00,
                    "is_refund": False,
                    "categories": ["travel_accommodation"],
                }
            ],
        },
    )

    with session_local() as db:
        result = StatementImporter(db).import_file(json_path, "2025-12")
        assert result.error is None

        txn = db.query(Transaction).one()
        assert txn.alert_kind == "high_value"
        assert txn.alert_status == "pending"


def test_large_refund_stays_linked_pending_when_original_charge_is_still_in_review(tmp_path):
    session_local = make_session_local()
    original_json = tmp_path / "original.json"
    refund_json = tmp_path / "refund.json"

    write_json(
        original_json,
        {
            "filename": "original.json",
            "bank_name": "UOB",
            "card_last_4": "7857",
            "statement_date": "2025-11-30",
            "transactions": [
                {
                    "transaction_date": "2025-11-22",
                    "merchant_name": "BIG TRAVEL BOOKING",
                    "amount": 250.00,
                    "is_refund": False,
                    "categories": ["tours"],
                }
            ],
        },
    )
    write_json(
        refund_json,
        {
            "filename": "refund.json",
            "bank_name": "UOB",
            "card_last_4": "7857",
            "statement_date": "2025-12-31",
            "transactions": [
                {
                    "transaction_date": "2025-12-02",
                    "merchant_name": "BIG TRAVEL BOOKING",
                    "amount": -250.00,
                    "is_refund": True,
                    "categories": [],
                }
            ],
        },
    )

    with session_local() as db:
        importer = StatementImporter(db)
        importer.import_file(original_json, "2025-11")
        result = importer.import_file(refund_json, "2025-12")
        assert result.refunds_auto_matched == 1

        refund = db.query(Transaction).filter(Transaction.amount == -250.00).one()
        assert refund.assignment_method == "refund_linked_pending"
        assert refund.review_origin_method == "refund_auto_match"
        assert refund.needs_review is True
        assert refund.alert_kind == "high_value"
        assert refund.alert_status == "pending"


def test_large_account_statement_row_creates_high_value_alert(tmp_path):
    session_local = make_session_local()
    json_path = tmp_path / "account.json"
    write_json(
        json_path,
        {
            "filename": "account.json",
            "bank_name": "UOB",
            "account_number_last_4": "5776",
            "account_name": "KRISFLYER UOB ACCOUNT",
            "statement_date": "2025-09-30",
            "transactions": [
                {
                    "transaction_date": "2025-09-05",
                    "merchant_name": "INCOME 92924089",
                    "amount": 1380.00,
                    "transaction_type": "debit",
                    "categories": [],
                }
            ],
        },
    )

    with session_local() as db:
        result = StatementImporter(db).import_file(json_path, "2025-09")
        assert result.error is None

        txn = db.query(Transaction).one()
        assert txn.amount == -1380.00
        assert txn.is_refund is False
        assert txn.transaction_type == "debit"
        assert txn.alert_kind == "high_value"
        assert txn.alert_status == "pending"


def test_large_account_credit_does_not_create_high_value_alert(tmp_path):
    session_local = make_session_local()
    json_path = tmp_path / "account_credit.json"
    write_json(
        json_path,
        {
            "filename": "account_credit.json",
            "bank_name": "UOB",
            "account_number_last_4": "5776",
            "account_name": "KRISFLYER UOB ACCOUNT",
            "statement_date": "2025-09-30",
            "transactions": [
                {
                    "transaction_date": "2025-09-05",
                    "merchant_name": "Funds Transfer",
                    "amount": 1000.00,
                    "transaction_type": "credit",
                    "categories": [],
                }
            ],
        },
    )

    with session_local() as db:
        result = StatementImporter(db).import_file(json_path, "2025-09")
        assert result.error is None

        txn = db.query(Transaction).one()
        assert txn.amount == -1000.00
        assert txn.transaction_type == "credit"
        assert txn.alert_kind is None
        assert txn.alert_status is None


def test_high_value_alert_applies_to_foo_wah_liang_card(tmp_path):
    session_local = make_session_local()
    json_path = tmp_path / "dad_card.json"
    write_json(
        json_path,
        {
            "filename": "dad_card.json",
            "bank_name": "UOB",
            "card_last_4": "4474",
            "statement_date": "2025-12-31",
            "transactions": [
                {
                    "transaction_date": "2025-12-03",
                    "merchant_name": "BIG FLIGHT BOOKING",
                    "amount": 333.00,
                    "categories": ["flights"],
                }
            ],
        },
    )

    with session_local() as db:
        seed_card_owner(db, person_name="foo_wah_liang", relationship_type="parent", card_last_4="4474")
        result = StatementImporter(db).import_file(json_path, "2025-12")
        assert result.error is None

        txn = db.query(Transaction).one()
        assert txn.alert_kind == "high_value"
        assert txn.alert_status == "pending"


def test_high_value_alert_applies_to_chan_zelin_card(tmp_path):
    session_local = make_session_local()
    json_path = tmp_path / "wife_card.json"
    write_json(
        json_path,
        {
            "filename": "wife_card.json",
            "bank_name": "Citibank",
            "card_last_4": "2065",
            "statement_date": "2025-12-31",
            "transactions": [
                {
                    "transaction_date": "2025-12-04",
                    "merchant_name": "BIG HOTEL BOOKING",
                    "amount": 222.00,
                    "categories": ["travel_accommodation"],
                }
            ],
        },
    )

    with session_local() as db:
        seed_card_owner(db, person_name="chan_zelin", relationship_type="spouse", card_last_4="2065")
        result = StatementImporter(db).import_file(json_path, "2025-12")
        assert result.error is None

        txn = db.query(Transaction).one()
        assert txn.alert_kind == "high_value"
        assert txn.alert_status == "pending"


def test_card_fee_over_threshold_stays_card_fee_alert(tmp_path):
    session_local = make_session_local()
    json_path = tmp_path / "fee.json"
    write_json(
        json_path,
        {
            "filename": "fee.json",
            "bank_name": "Maybank",
            "card_last_4": "0005",
            "statement_date": "2025-12-31",
            "transactions": [
                {
                    "transaction_date": "2025-12-24",
                    "merchant_name": "ANNUAL FEE",
                    "amount": 240.00,
                    "is_refund": False,
                    "categories": [],
                }
            ],
        },
    )

    with session_local() as db:
        result = StatementImporter(db).import_file(json_path, "2025-12")
        assert result.error is None

        txn = db.query(Transaction).one()
        assert txn.categories == ["card_fees"]
        assert txn.alert_kind == "card_fee"
        assert txn.alert_status == "pending"

import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import Bill, BillLineItem, Person, Statement, Transaction, TransactionSplit
from app.services.account_statement_service import repair_account_statement_history
from app.services.bill_generator import BillGenerator
from app.services.importer import StatementImporter


def make_session_local():
    engine = create_engine("sqlite:///:memory:")
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    return session_local


def create_people(db):
    dad = Person(name="foo_wah_liang", relationship_type="parent", card_last_4_digits=["4474"], is_auto_created=False)
    self_person = Person(name="foo_chi_jao", relationship_type="self", card_last_4_digits=["5776"], is_auto_created=True)
    wife = Person(name="chan_zelin", relationship_type="spouse", card_last_4_digits=["0203"], is_auto_created=False)
    db.add_all([dad, self_person, wife])
    db.commit()
    return dad, self_person, wife


def test_account_statement_import_inverts_amount_signs_and_skips_refund_matching(tmp_path):
    session_local = make_session_local()
    json_path = tmp_path / "account.json"
    json_path.write_text(
        json.dumps(
            {
                "filename": "account.json",
                "bank_name": "UOB",
                "account_number_last_4": "5776",
                "account_name": "UOB One Account",
                "statement_date": "2026-02-28",
                "transactions": [
                    {
                        "transaction_date": "2026-02-10",
                        "merchant_name": "NEE SOON TOWN COUNCIL",
                        "amount": -35.30,
                        "categories": ["town_council"],
                    },
                    {
                        "transaction_date": "2026-02-28",
                        "merchant_name": "Interest Credit",
                        "amount": 0.03,
                        "categories": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with session_local() as db:
        create_people(db)
        importer = StatementImporter(db)
        result = importer.import_file(json_path, "2026-02")

        assert result.refunds_auto_matched == 0
        rows = db.query(Transaction).order_by(Transaction.transaction_date).all()
        assert [row.amount for row in rows] == [35.30, -0.03]
        assert all(row.is_refund is False for row in rows)
        assert all(not (row.assignment_method or "").startswith("refund_") for row in rows)


def test_repair_account_statement_history_inverts_existing_rows_and_deletes_draft_bills(tmp_path):
    session_local = make_session_local()
    json_path = tmp_path / "account.json"
    json_path.write_text(
        json.dumps(
            {
                "filename": "account.json",
                "bank_name": "UOB",
                "account_number_last_4": "5776",
                "account_name": "UOB One Account",
                "statement_date": "2026-02-28",
                "transactions": [
                    {
                        "transaction_date": "2026-02-10",
                        "merchant_name": "NEE SOON TOWN COUNCIL",
                        "amount": -70.60,
                        "categories": ["town_council"],
                    },
                    {
                        "transaction_date": "2026-02-28",
                        "merchant_name": "Interest Credit",
                        "amount": 0.03,
                        "categories": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with session_local() as db:
        dad, self_person, wife = create_people(db)
        statement = Statement(
            filename="account.json",
            bank_name="UOB",
            card_last_4="5776",
            card_name="UOB One Account",
            statement_date=date(2026, 2, 28),
            billing_month="2026-02",
            raw_file_path=str(json_path),
        )
        db.add(statement)
        db.flush()

        shared_txn = Transaction(
            statement_id=statement.id,
            billing_month="2026-02",
            transaction_date=date(2026, 2, 10),
            merchant_name="NEE SOON TOWN COUNCIL",
            amount=-70.60,
            assignment_method="shared_manual",
            needs_review=False,
        )
        shared_txn.transaction_splits = [
            TransactionSplit(person_id=self_person.id, split_amount=-35.30, split_percent=50.0, sort_order=0),
            TransactionSplit(person_id=wife.id, split_amount=-35.30, split_percent=50.0, sort_order=1),
        ]

        credit_txn = Transaction(
            statement_id=statement.id,
            billing_month="2026-02",
            transaction_date=date(2026, 2, 28),
            merchant_name="Interest Credit",
            amount=0.03,
            assignment_method="refund_orphan",
            needs_review=True,
            is_refund=True,
        )

        db.add_all([shared_txn, credit_txn])
        db.flush()

        draft_bill = Bill(
            person_id=wife.id,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 3, 1),
            total_amount=-35.30,
            status="draft",
        )
        db.add(draft_bill)
        db.flush()
        db.add(BillLineItem(bill_id=draft_bill.id, transaction_id=shared_txn.id, amount=-35.30, description=shared_txn.merchant_name))
        db.commit()

        result = repair_account_statement_history(db)

        db.refresh(shared_txn)
        db.refresh(credit_txn)
        assert result.repaired_statements == 1
        assert shared_txn.amount == 70.60
        assert [split.split_amount for split in shared_txn.transaction_splits] == [35.30, 35.30]
        assert credit_txn.amount == -0.03
        assert credit_txn.is_refund is False
        assert not (credit_txn.assignment_method or "").startswith("refund_")
        assert result.deleted_draft_bill_ids == [draft_bill.id]
        assert db.query(Bill).count() == 0


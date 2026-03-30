import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import Statement, Transaction
from app.services.importer import StatementImporter


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

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import Transaction
from app.services.importer import StatementImporter


def test_gst_reversal_without_categories_routes_to_alert_resolver(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    fee_json = tmp_path / "fee.json"
    fee_json.write_text(
        json.dumps(
            {
                "filename": "fee.json",
                "bank_name": "Maybank",
                "card_last_4": "0005",
                "statement_date": "2025-12-31",
                "transactions": [
                    {
                        "transaction_date": "2025-12-24",
                        "merchant_name": "GST @ 9 %",
                        "amount": 21.60,
                        "is_refund": False,
                        "categories": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    reversal_json = tmp_path / "reversal.json"
    reversal_json.write_text(
        json.dumps(
            {
                "filename": "reversal.json",
                "bank_name": "Maybank",
                "card_last_4": "0005",
                "statement_date": "2026-01-31",
                "transactions": [
                    {
                        "transaction_date": "2026-01-13",
                        "merchant_name": "GST @ 9 % REVERSAL",
                        "amount": -21.60,
                        "is_refund": True,
                        "categories": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with SessionLocal() as db:
        importer = StatementImporter(db)

        fee_result = importer.import_file(fee_json, "2025-12")
        assert fee_result.alerts_created == 1

        reversal_result = importer.import_file(reversal_json, "2026-01")
        assert reversal_result.alerts_auto_resolved == 1
        assert reversal_result.refunds_auto_matched == 0

        fee = db.query(Transaction).filter(Transaction.amount == 21.60).one()
        reversal = db.query(Transaction).filter(Transaction.amount == -21.60).one()

        assert fee.categories == ["card_fees"]
        assert reversal.categories == ["card_fees"]
        assert fee.alert_status == "resolved"
        assert fee.resolved_by_transaction_id == reversal.id
        assert reversal.alert_status == "resolved"
        assert reversal.needs_review is False
        assert reversal.assignment_method is None


def test_maybank_billed_annual_fee_credit_adjustment_resolves_as_card_fee(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    fee_json = tmp_path / "fee_annual.json"
    fee_json.write_text(
        json.dumps(
            {
                "filename": "fee_annual.json",
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
            }
        ),
        encoding="utf-8",
    )

    reversal_json = tmp_path / "reversal_annual.json"
    reversal_json.write_text(
        json.dumps(
            {
                "filename": "reversal_annual.json",
                "bank_name": "Maybank",
                "card_last_4": "0005",
                "statement_date": "2026-01-31",
                "transactions": [
                    {
                        "transaction_date": "2025-12-24",
                        "merchant_name": "BILLED ANNUAL FEE CREDIT ADJUSTMENT",
                        "amount": -240.00,
                        "is_refund": True,
                        "categories": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with SessionLocal() as db:
        importer = StatementImporter(db)

        fee_result = importer.import_file(fee_json, "2025-12")
        assert fee_result.alerts_created == 1

        reversal_result = importer.import_file(reversal_json, "2026-01")
        assert reversal_result.alerts_auto_resolved == 1
        assert reversal_result.refunds_auto_matched == 0

        fee = db.query(Transaction).filter(Transaction.amount == 240.00).one()
        reversal = db.query(Transaction).filter(Transaction.amount == -240.00).one()

        assert fee.categories == ["card_fees"]
        assert reversal.categories == ["card_fees"]
        assert fee.alert_status == "resolved"
        assert fee.resolved_by_transaction_id == reversal.id
        assert reversal.alert_status == "resolved"
        assert reversal.needs_review is False
        assert reversal.assignment_method is None

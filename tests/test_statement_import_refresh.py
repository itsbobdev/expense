import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import Statement, Transaction
from app.services.importer import StatementImporter


def test_refresh_replaces_existing_statement_and_transactions(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    json_path = tmp_path / "statement.json"
    json_path.write_text(
        json.dumps(
            {
                "filename": "statement.json",
                "bank_name": "Citibank",
                "card_last_4": "6265",
                "statement_date": "2025-11-09",
                "total_charges": 1025.38,
                "transactions": [
                    {
                        "transaction_date": "2025-10-11",
                        "merchant_name": "OLD MERCHANT",
                        "amount": 1025.38,
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
        initial = importer.import_file(json_path, "2025-11")
        assert initial.skipped is False
        first_statement_hash = db.query(Statement).one().pdf_hash

        json_path.write_text(
            json.dumps(
                {
                    "filename": "statement.json",
                    "bank_name": "Citibank",
                    "card_last_4": "6265",
                    "statement_date": "2025-11-09",
                    "total_charges": 906.70,
                    "transactions": [
                        {
                            "transaction_date": "2025-10-11",
                            "merchant_name": "NEW MERCHANT",
                            "amount": 906.70,
                            "is_refund": False,
                            "categories": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        refreshed = importer.import_file(json_path, "2025-11", refresh_existing=True)
        assert refreshed.skipped is False
        assert refreshed.transactions_imported == 1

        statements = db.query(Statement).all()
        transactions = db.query(Transaction).all()

        assert len(statements) == 1
        assert len(transactions) == 1
        assert statements[0].total_charges == 906.70
        assert statements[0].pdf_hash != first_statement_hash
        assert transactions[0].merchant_name == "NEW MERCHANT"
        assert transactions[0].statement_id == statements[0].id


def test_refresh_replaces_existing_statement_when_corrected_identity_changes(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    json_path = tmp_path / "statement.json"
    json_path.write_text(
        json.dumps(
            {
                "filename": "statement.json",
                "bank_name": "UOB",
                "card_last_4": "1111",
                "statement_date": "2025-10-01",
                "total_charges": 50.0,
                "transactions": [
                    {
                        "transaction_date": "2025-09-28",
                        "merchant_name": "OLD ENTRY",
                        "amount": 50.0,
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
        initial = importer.import_file(json_path, "2025-10")
        assert initial.skipped is False

        json_path.write_text(
            json.dumps(
                {
                    "filename": "statement.json",
                    "bank_name": "UOB",
                    "card_last_4": "4919",
                    "statement_date": "2025-10-24",
                    "total_charges": 90.0,
                    "transactions": [
                        {
                            "transaction_date": "2025-10-10",
                            "merchant_name": "CORRECTED ENTRY",
                            "amount": 90.0,
                            "is_refund": False,
                            "categories": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        refreshed = importer.import_file(json_path, "2025-10", refresh_existing=True)
        assert refreshed.skipped is False
        assert refreshed.transactions_imported == 1

        statements = db.query(Statement).all()
        transactions = db.query(Transaction).all()

        assert len(statements) == 1
        assert len(transactions) == 1
        assert statements[0].card_last_4 == "4919"
        assert statements[0].statement_date.isoformat() == "2025-10-24"
        assert statements[0].raw_file_path == str(json_path.resolve())
        assert transactions[0].merchant_name == "CORRECTED ENTRY"

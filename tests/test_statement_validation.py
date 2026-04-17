import json
import shutil
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import Transaction
from app.services.importer import StatementImporter


SAMPLE_DIR = Path(r"D:\D drive\GitHub\expense\statements\2025\09\uob")
SAMPLE_JSON = SAMPLE_DIR / "2025_sep_uob_ladys_solitaire_card_foo_chi_jao_5750.json"
SAMPLE_PDF = SAMPLE_DIR / "2025_sep_uob_creditcard_combined.pdf"


def make_session_local():
    engine = create_engine("sqlite:///:memory:")
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_local


def _write_sample_pair(tmp_path: Path, payload: dict) -> Path:
    shutil.copy2(SAMPLE_PDF, tmp_path / SAMPLE_PDF.name)
    json_path = tmp_path / SAMPLE_JSON.name
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    return json_path


def test_import_rejects_broken_uob_credit_rows(tmp_path):
    payload = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
    payload["transactions"] = [
        txn
        for txn in payload["transactions"]
        if not (txn.get("is_refund") and "HILTON ADVPURCH8002367" in (txn.get("merchant_name") or ""))
    ]
    json_path = _write_sample_pair(tmp_path, payload)

    session_local = make_session_local()
    with session_local() as db:
        result = StatementImporter(db).import_file(json_path, "2025-09")
        assert result.error is not None
        assert "missing uob credit rows" in result.error.lower()


def test_import_accepts_corrected_uob_credit_rows(tmp_path):
    payload = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
    json_path = _write_sample_pair(tmp_path, payload)

    session_local = make_session_local()
    with session_local() as db:
        result = StatementImporter(db).import_file(json_path, "2025-09")
        assert result.error is None

        refunds = (
            db.query(Transaction)
            .filter(Transaction.is_refund == True)
            .order_by(Transaction.amount)
            .all()
        )
        assert [round(txn.amount, 2) for txn in refunds] == [-1957.53, -938.97, -478.58]


def test_import_can_bypass_validation_for_restore_mode(tmp_path):
    payload = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
    payload["transactions"] = [
        txn
        for txn in payload["transactions"]
        if not (txn.get("is_refund") and "HILTON ADVPURCH8002367" in (txn.get("merchant_name") or ""))
    ]
    json_path = _write_sample_pair(tmp_path, payload)

    session_local = make_session_local()
    with session_local() as db:
        result = StatementImporter(db).import_file(
            json_path,
            "2025-09",
            allow_validation_errors=True,
        )
        assert result.error is None
        assert result.transactions_imported == len(payload["transactions"])

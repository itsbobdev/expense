"""
Import statement JSON files into the database.

Usage:
    python import_statements.py <json_file> [<json_file> ...]
    python import_statements.py statements/2026/02/citi/eStatement_Feb2026_6265.json

The JSON files are produced by the /extract-statement command.
The script is idempotent: re-importing the same PDF (identified by pdf_hash) is a no-op.
"""
import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Allow running from backend/ or repo root
sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal, init_db
from app.models import Statement, Transaction
from app.services.categorizer import TransactionCategorizer
from app.services.refund_handler import RefundHandler


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _compute_pdf_hash(json_path: Path, data: dict) -> str | None:
    """
    Try to find the source PDF next to the JSON file and hash it.
    Falls back to hashing the JSON content itself so dedup still works.
    """
    # Guess PDF filename from json filename: strip card suffix, replace .json
    # e.g. eStatement_Feb2026_6265.json -> eStatement_Feb2026.pdf
    stem = json_path.stem
    # Remove trailing _XXXX (card last 4) if present
    parts = stem.rsplit("_", 1)
    pdf_candidate = json_path.parent / (parts[0] + ".pdf") if len(parts) == 2 else None

    if pdf_candidate and pdf_candidate.exists():
        content = pdf_candidate.read_bytes()
    else:
        # Hash the canonical JSON content as fallback
        content = json.dumps(data, sort_keys=True).encode()

    return hashlib.sha256(content).hexdigest()


def import_json(json_path: Path, db) -> dict:
    """
    Import one statement JSON file.

    Returns a summary dict:
      { skipped, total, auto_assigned, needs_review, statement_id }
    """
    raw = json_path.read_text(encoding="utf-8")
    data = json.loads(raw)

    pdf_hash = _compute_pdf_hash(json_path, data)

    # --- Dedup check ---
    if pdf_hash:
        existing = db.query(Statement).filter(Statement.pdf_hash == pdf_hash).first()
        if existing:
            print(f"  [SKIP] Already imported (statement id={existing.id}, hash={pdf_hash[:12]}…)")
            return {"skipped": True}

    # --- Build Statement record ---
    stmt = Statement(
        filename=data.get("filename", json_path.name),
        bank_name=data.get("bank_name"),
        card_last_4=data.get("card_last_4", "XXXX"),
        card_name=data.get("card_name"),
        statement_date=_parse_date(data.get("statement_date")),
        period_start=_parse_date(data.get("period_start")),
        period_end=_parse_date(data.get("period_end")),
        pdf_hash=pdf_hash,
        total_charges=data.get("total_charges"),
        status="pending",
        raw_file_path=str(json_path),
    )
    db.add(stmt)
    db.flush()  # get stmt.id without full commit

    # --- Build Transaction records ---
    transactions_data = data.get("transactions", [])
    categorizer = TransactionCategorizer(db)
    refund_handler = RefundHandler(db)

    auto_assigned = 0
    needs_review = 0
    created_transactions = []

    for tx_data in transactions_data:
        amount = float(tx_data.get("amount", 0))
        ccy_fee = tx_data.get("ccy_fee")

        tx = Transaction(
            statement_id=stmt.id,
            transaction_date=_parse_date(tx_data.get("transaction_date")),
            merchant_name=tx_data.get("merchant_name", "UNKNOWN"),
            raw_description=tx_data.get("raw_description"),
            amount=amount,
            ccy_fee=float(ccy_fee) if ccy_fee is not None else None,
            is_refund=bool(tx_data.get("is_refund", False)),
            country_code=tx_data.get("country_code"),
            location=tx_data.get("location"),
        )
        db.add(tx)
        db.flush()  # get tx.id

        # Categorize
        result = categorizer.categorize(tx)
        tx.assigned_to_person_id = result.person_id
        tx.assignment_confidence = result.confidence
        tx.assignment_method = result.method
        tx.needs_review = result.needs_review
        if result.blacklist_category_id:
            tx.blacklist_category_id = result.blacklist_category_id

        created_transactions.append(tx)

        if result.needs_review:
            needs_review += 1
        else:
            auto_assigned += 1

    db.flush()

    # --- Process refunds ---
    for tx in created_transactions:
        if tx.is_refund or tx.amount < 0:
            refund_handler.process_refund(tx)

    stmt.status = "processed"
    stmt.processed_at = datetime.utcnow()
    db.commit()

    return {
        "skipped": False,
        "statement_id": stmt.id,
        "total": len(created_transactions),
        "auto_assigned": auto_assigned,
        "needs_review": needs_review,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Import statement JSON files into the expense tracker database."
    )
    parser.add_argument(
        "json_files",
        nargs="+",
        metavar="JSON_FILE",
        help="Path(s) to statement JSON file(s) produced by /extract-statement",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    try:
        total_imported = 0
        total_skipped = 0

        for path_str in args.json_files:
            json_path = Path(path_str)
            if not json_path.exists():
                print(f"[ERROR] File not found: {json_path}")
                continue

            print(f"\nImporting: {json_path}")
            result = import_json(json_path, db)

            if result.get("skipped"):
                total_skipped += 1
            else:
                total_imported += 1
                sid = result["statement_id"]
                total = result["total"]
                auto = result["auto_assigned"]
                review = result["needs_review"]
                print(f"  [OK] statement_id={sid} | {total} transactions | "
                      f"{auto} auto-assigned | {review} needs review")

        print(f"\nDone. Imported: {total_imported}, Skipped (already imported): {total_skipped}")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

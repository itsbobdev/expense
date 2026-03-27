"""
Statement Importer Service

Imports JSON statement files from statements/YYYY/MM/bank/ into the database,
then runs categorization and refund matching on each transaction.
"""
import json
import hashlib
import logging
from pathlib import Path
from datetime import date, datetime
from typing import List, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Statement, Transaction
from app.services.categorizer import TransactionCategorizer
from app.services.refund_handler import RefundHandler
from app.services.alert_resolver import AlertResolver
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Result of importing a single JSON file."""
    filename: str
    billing_month: str
    statement_id: Optional[int]
    transactions_imported: int
    transactions_flagged: int
    refunds_auto_matched: int
    alerts_created: int
    alerts_auto_resolved: int
    skipped: bool
    skip_reason: Optional[str] = None
    error: Optional[str] = None


@dataclass
class MonthImportResult:
    """Result of importing all files for a billing month."""
    billing_month: str
    files_imported: int
    files_skipped: int
    files_errored: int
    total_transactions: int
    total_flagged: int
    total_refunds_matched: int
    total_alerts_created: int
    total_alerts_resolved: int
    file_results: List[ImportResult]


class StatementImporter:
    """Imports JSON statement files and runs the categorization pipeline."""

    def __init__(self, db: Session):
        self.db = db
        self.categorizer = TransactionCategorizer(db)
        self.refund_handler = RefundHandler(db)
        self.alert_resolver = AlertResolver(db)

    def import_month(self, year: int, month: int) -> MonthImportResult:
        """
        Import all JSON statement files for a given billing month.

        Scans statements/YYYY/MM/ for all bank subdirectories and JSON files.

        Args:
            year: 4-digit year (e.g. 2026)
            month: 1-12

        Returns:
            MonthImportResult with summary and per-file details
        """
        billing_month = f"{year:04d}-{month:02d}"
        month_dir = settings.statements_dir / f"{year:04d}" / f"{month:02d}"

        if not month_dir.exists():
            return MonthImportResult(
                billing_month=billing_month,
                files_imported=0, files_skipped=0, files_errored=0,
                total_transactions=0, total_flagged=0, total_refunds_matched=0,
                file_results=[],
            )

        # Collect all JSON files across bank subdirectories
        json_files = sorted(month_dir.glob("**/*.json"))
        # Exclude .claude/ directory files
        json_files = [f for f in json_files if ".claude" not in str(f)]

        file_results = []
        for json_path in json_files:
            result = self.import_file(json_path, billing_month)
            file_results.append(result)

        imported = [r for r in file_results if not r.skipped and not r.error]
        skipped = [r for r in file_results if r.skipped]
        errored = [r for r in file_results if r.error]

        return MonthImportResult(
            billing_month=billing_month,
            files_imported=len(imported),
            files_skipped=len(skipped),
            files_errored=len(errored),
            total_transactions=sum(r.transactions_imported for r in imported),
            total_flagged=sum(r.transactions_flagged for r in imported),
            total_refunds_matched=sum(r.refunds_auto_matched for r in imported),
            total_alerts_created=sum(r.alerts_created for r in imported),
            total_alerts_resolved=sum(r.alerts_auto_resolved for r in imported),
            file_results=file_results,
        )

    def import_file(self, json_path: Path, billing_month: str) -> ImportResult:
        """
        Import a single JSON statement file.

        Creates a Statement record and Transaction records, then runs
        categorization on each transaction and refund matching on refunds.

        Args:
            json_path: Path to the JSON file
            billing_month: Billing month string "YYYY-MM"

        Returns:
            ImportResult with details
        """
        filename = json_path.name

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            return ImportResult(
                filename=filename, billing_month=billing_month,
                statement_id=None, transactions_imported=0,
                transactions_flagged=0, refunds_auto_matched=0,
                alerts_created=0, alerts_auto_resolved=0,
                skipped=False, error=str(e),
            )

        # Compute hash for dedup (hash the JSON content itself)
        json_content = json.dumps(data, sort_keys=True)
        content_hash = hashlib.sha256(json_content.encode("utf-8")).hexdigest()

        # Check for duplicate import
        existing = self.db.query(Statement).filter(
            Statement.pdf_hash == content_hash
        ).first()
        if existing:
            return ImportResult(
                filename=filename, billing_month=billing_month,
                statement_id=existing.id, transactions_imported=0,
                transactions_flagged=0, refunds_auto_matched=0,
                alerts_created=0, alerts_auto_resolved=0,
                skipped=True, skip_reason="duplicate (content hash match)",
            )

        # Also check by (bank_name, card_last_4, statement_date) as fallback dedup
        statement_date = self._parse_date(data.get("statement_date", ""))
        card_last_4 = data.get("card_last_4") or data.get("account_number_last_4")
        if statement_date:
            existing_by_key = self.db.query(Statement).filter(
                Statement.bank_name == data.get("bank_name"),
                Statement.card_last_4 == card_last_4,
                Statement.statement_date == statement_date,
                Statement.billing_month == billing_month,
            ).first()
            if existing_by_key:
                return ImportResult(
                    filename=filename, billing_month=billing_month,
                    statement_id=existing_by_key.id, transactions_imported=0,
                    transactions_flagged=0, refunds_auto_matched=0,
                    alerts_created=0, alerts_auto_resolved=0,
                    skipped=True,
                    skip_reason="duplicate (bank/card/date/month match)",
                )

        # Create Statement record
        statement = Statement(
            filename=data.get("filename", filename),
            bank_name=data.get("bank_name"),
            card_last_4=data.get("card_last_4") or data.get("account_number_last_4", "0000"),
            card_name=data.get("card_name") or data.get("account_name"),
            statement_date=statement_date or date.today(),
            billing_month=billing_month,
            period_start=self._parse_date(data.get("period_start")),
            period_end=self._parse_date(data.get("period_end")),
            pdf_hash=content_hash,
            total_charges=data.get("total_charges"),
            status="pending",
            raw_file_path=str(json_path),
        )
        self.db.add(statement)
        self.db.flush()  # Get statement.id without committing

        # Create Transaction records
        transactions_data = data.get("transactions", [])
        transactions = []
        for txn_data in transactions_data:
            txn = Transaction(
                statement_id=statement.id,
                billing_month=billing_month,
                transaction_date=self._parse_date(txn_data.get("transaction_date")) or statement_date or date.today(),
                merchant_name=txn_data.get("merchant_name") or txn_data.get("description", "UNKNOWN"),
                raw_description=txn_data.get("raw_description"),
                amount=txn_data.get("amount", 0.0),
                ccy_fee=txn_data.get("ccy_fee"),
                is_refund=txn_data.get("is_refund", False),
                categories=txn_data.get("categories", []),
                country_code=txn_data.get("country_code"),
                location=txn_data.get("location"),
            )
            self.db.add(txn)
            transactions.append(txn)

        self.db.flush()  # Get transaction IDs

        # Run categorization on non-refund transactions
        flagged_count = 0
        alerts_created = 0
        for txn in transactions:
            if not txn.is_refund:
                result = self.categorizer.categorize(txn)
                txn.assigned_to_person_id = result.person_id
                txn.assignment_confidence = result.confidence
                txn.assignment_method = result.method
                txn.needs_review = result.needs_review
                txn.blacklist_category_id = result.blacklist_category_id
                txn.alert_status = result.alert_status
                if result.needs_review:
                    flagged_count += 1
                if result.alert_status == 'pending':
                    alerts_created += 1

        self.db.flush()  # Ensure IDs available for alert_resolver

        # Run alert resolver on card_fees transactions (GST linking + auto-resolve)
        alerts_resolved = 0
        for txn in transactions:
            categories = txn.categories or []
            if 'card_fees' in categories:
                if self.alert_resolver.process_card_fee(txn):
                    alerts_resolved += 1

        # Run refund matching on refund transactions (non-card_fees refunds)
        refunds_matched = 0
        for txn in transactions:
            if txn.is_refund:
                categories = txn.categories or []
                if 'card_fees' in categories:
                    continue  # already handled by alert_resolver
                if self.refund_handler.process_refund(txn):
                    refunds_matched += 1
                elif txn.needs_review:
                    flagged_count += 1

        statement.status = "processed"
        statement.processed_at = datetime.utcnow()
        self.db.commit()

        logger.info(
            "Imported %s: %d transactions (%d flagged, %d refunds matched, %d alerts, %d auto-resolved)",
            filename, len(transactions), flagged_count, refunds_matched, alerts_created, alerts_resolved,
        )

        return ImportResult(
            filename=filename,
            billing_month=billing_month,
            statement_id=statement.id,
            transactions_imported=len(transactions),
            transactions_flagged=flagged_count,
            refunds_auto_matched=refunds_matched,
            alerts_created=alerts_created,
            alerts_auto_resolved=alerts_resolved,
            skipped=False,
        )

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[date]:
        """Parse a date string in YYYY-MM-DD format."""
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

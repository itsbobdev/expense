"""
Statement Importer Service

Imports JSON statement files from statements/YYYY/MM/bank/ into the database,
then runs categorization and refund matching on each transaction.
"""
import re
import json
import hashlib
import logging
from pathlib import Path
from datetime import date, datetime
from typing import List, Optional, Tuple
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Statement, Transaction, BillLineItem, MLTrainingData
from app.services.account_statement_service import (
    is_account_statement_data,
    normalize_statement_amount,
)
from app.services.categorizer import TransactionCategorizer
from app.services.refund_handler import RefundHandler
from app.services.alert_resolver import AlertResolver, looks_like_card_fee
from app.config import settings

# Patterns that identify cashback reward transactions (not merchant refunds)
_REWARD_PATTERNS = [
    re.compile(r'^\d+%\s*CASHBACK$', re.IGNORECASE),   # "8% CASHBACK"
    re.compile(r'^OTHER\s+CASHBACK$', re.IGNORECASE),
    re.compile(r'^UOB\s+EVOL\s+Card\s+Cashback', re.IGNORECASE),
    re.compile(r'^UOB\s+Absolute\s+Cashback', re.IGNORECASE),
]


def _is_reward_transaction(merchant_name: str) -> bool:
    """Return True if merchant_name matches a known cashback reward pattern."""
    return any(p.match(merchant_name or '') for p in _REWARD_PATTERNS)


def _normalize_categories(txn_data: dict, merchant_name: str) -> list[str]:
    """Apply importer-side fallback categories when extraction misses them."""
    categories = list(txn_data.get("categories", []) or [])
    if 'card_fees' not in categories and looks_like_card_fee(merchant_name):
        categories.append('card_fees')
    return categories

logger = logging.getLogger(__name__)


def _normalize_path_value(path_value: str | Path | None) -> str:
    """Normalize a filesystem path string for case-insensitive comparisons."""
    if not path_value:
        return ""
    return str(path_value).replace("\\", "/").strip().casefold()


def _statement_path_suffix(path_value: str | Path | None) -> str:
    """Return a normalized statements/.. suffix when present, else the basename."""
    normalized = _normalize_path_value(path_value)
    if not normalized:
        return ""
    marker = "/statements/"
    if marker in normalized:
        return "statements/" + normalized.split(marker, 1)[1]
    return Path(str(path_value)).name.casefold()


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

    def import_month(self, year: int, month: int, refresh_existing: bool = False) -> MonthImportResult:
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
                total_alerts_created=0, total_alerts_resolved=0,
                file_results=[],
            )

        # Collect all JSON files across bank subdirectories
        json_files = sorted(month_dir.glob("**/*.json"))
        # Exclude .claude/ directory files
        json_files = [f for f in json_files if ".claude" not in str(f)]

        file_results = []
        for json_path in json_files:
            result = self.import_file(json_path, billing_month, refresh_existing=refresh_existing)
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

    def import_file(self, json_path: Path, billing_month: str, refresh_existing: bool = False) -> ImportResult:
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

        existing, skip_reason, refresh_error = self._find_existing_statement(
            data=data,
            json_path=json_path,
            billing_month=billing_month,
            content_hash=content_hash,
            refresh_existing=refresh_existing,
        )
        if refresh_error:
            return ImportResult(
                filename=filename, billing_month=billing_month,
                statement_id=None, transactions_imported=0,
                transactions_flagged=0, refunds_auto_matched=0,
                alerts_created=0, alerts_auto_resolved=0,
                skipped=False, error=refresh_error,
            )
        if existing:
            if refresh_existing:
                self._replace_statement(existing)
            else:
                return ImportResult(
                    filename=filename, billing_month=billing_month,
                    statement_id=existing.id, transactions_imported=0,
                    transactions_flagged=0, refunds_auto_matched=0,
                    alerts_created=0, alerts_auto_resolved=0,
                    skipped=True, skip_reason=skip_reason,
                )

        # Recompute after any replacement work and proceed with fresh import.
        statement_date = self._parse_date(data.get("statement_date", ""))
        is_account_statement = is_account_statement_data(data)

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
            raw_file_path=str(json_path.resolve()),
        )
        self.db.add(statement)
        self.db.flush()  # Get statement.id without committing

        # Create Transaction records
        transactions_data = data.get("transactions", [])
        transactions = []
        for txn_data in transactions_data:
            merchant_name = txn_data.get("merchant_name") or txn_data.get("description", "UNKNOWN")
            is_reward = txn_data.get("is_reward", False) or _is_reward_transaction(merchant_name)
            is_refund = False if (is_reward or is_account_statement) else txn_data.get("is_refund", False)
            categories = _normalize_categories(txn_data, merchant_name)
            amount = normalize_statement_amount(txn_data.get("amount", 0.0), is_account_statement)

            txn = Transaction(
                statement_id=statement.id,
                billing_month=billing_month,
                transaction_date=self._parse_date(txn_data.get("transaction_date")) or statement_date or date.today(),
                merchant_name=merchant_name,
                raw_description=txn_data.get("raw_description"),
                amount=amount,
                ccy_fee=txn_data.get("ccy_fee"),
                is_refund=is_refund,
                is_reward=is_reward,
                reward_type=txn_data.get("reward_type", "cashback") if is_reward else None,
                categories=categories,
                country_code=txn_data.get("country_code"),
                location=txn_data.get("location"),
            )
            self.db.add(txn)
            transactions.append(txn)

        self.db.flush()  # Get transaction IDs

        # Run categorization on non-refund transactions
        # Reward transactions still go through categorizer (for person assignment)
        # but always have needs_review=False overridden.
        flagged_count = 0
        alerts_created = 0
        for txn in transactions:
            if not txn.is_refund:
                result = self.categorizer.categorize(txn)
                txn.assigned_to_person_id = result.person_id
                txn.assignment_confidence = result.confidence
                txn.assignment_method = result.method
                txn.review_origin_method = result.method if result.needs_review else None
                if txn.is_reward:
                    txn.needs_review = False
                    txn.blacklist_category_id = None
                    txn.alert_status = None
                else:
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

        # Run refund matching on refund transactions (non-card_fees refunds, non-rewards)
        refunds_matched = 0
        for txn in transactions:
            if txn.is_refund and not txn.is_reward:
                categories = txn.categories or []
                if 'card_fees' in categories:
                    continue  # already handled by alert_resolver
                if self.refund_handler.process_refund(txn):
                    refunds_matched += 1
                elif txn.needs_review:
                    flagged_count += 1

        # Retry older orphan refunds after newly imported original charges land.
        for txn in transactions:
            if txn.is_refund or txn.is_reward:
                continue
            refunds_matched += self.refund_handler.reconcile_refunds_for_original(txn)

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

    def _replace_statement(self, statement: Statement) -> None:
        """Replace an existing imported statement and its transactions."""
        transaction_ids = [txn.id for txn in statement.transactions]
        if transaction_ids:
            self.db.query(BillLineItem).filter(
                BillLineItem.transaction_id.in_(transaction_ids)
            ).update(
                {BillLineItem.transaction_id: None},
                synchronize_session=False,
            )
            self.db.query(MLTrainingData).filter(
                MLTrainingData.transaction_id.in_(transaction_ids)
            ).delete(synchronize_session=False)
            self.db.query(Transaction).filter(
                Transaction.original_transaction_id.in_(transaction_ids)
            ).update(
                {Transaction.original_transaction_id: None},
                synchronize_session=False,
            )
            self.db.query(Transaction).filter(
                Transaction.parent_transaction_id.in_(transaction_ids)
            ).update(
                {Transaction.parent_transaction_id: None},
                synchronize_session=False,
            )
            self.db.query(Transaction).filter(
                Transaction.resolved_by_transaction_id.in_(transaction_ids)
            ).update(
                {
                    Transaction.resolved_by_transaction_id: None,
                    Transaction.resolved_method: None,
                },
                synchronize_session=False,
            )
        self.db.delete(statement)
        self.db.flush()

    def _find_existing_statement(
        self,
        data: dict,
        json_path: Path,
        billing_month: str,
        content_hash: str,
        refresh_existing: bool,
    ) -> tuple[Optional[Statement], Optional[str], Optional[str]]:
        existing = self.db.query(Statement).filter(
            Statement.pdf_hash == content_hash
        ).first()
        if existing:
            return existing, "duplicate (content hash match)", None

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
                return existing_by_key, "duplicate (bank/card/date/month match)", None

        if not refresh_existing:
            return None, None, None

        existing_by_path, error = self._find_refresh_fallback_match(
            json_path=json_path,
            billing_month=billing_month,
            filename=data.get("filename") or json_path.name,
        )
        if error:
            return None, None, error
        if existing_by_path:
            return existing_by_path, "refresh match (path/filename fallback)", None
        return None, None, None

    def _find_refresh_fallback_match(
        self,
        json_path: Path,
        billing_month: str,
        filename: str,
    ) -> tuple[Optional[Statement], Optional[str]]:
        candidates = self.db.query(Statement).filter(
            Statement.billing_month == billing_month
        ).all()
        input_abs = _normalize_path_value(json_path.resolve())
        input_suffix = _statement_path_suffix(json_path.resolve())
        normalized_filename = str(filename).casefold()

        exact_path_matches: list[Statement] = []
        suffix_matches: list[Statement] = []
        filename_matches: list[Statement] = []

        for candidate in candidates:
            stored_raw_path = _normalize_path_value(candidate.raw_file_path)
            if stored_raw_path and stored_raw_path == input_abs:
                exact_path_matches.append(candidate)
                continue
            if stored_raw_path and input_suffix and stored_raw_path.endswith(input_suffix):
                suffix_matches.append(candidate)
                continue
            if (candidate.filename or "").casefold() == normalized_filename:
                filename_matches.append(candidate)

        if len(exact_path_matches) == 1:
            return exact_path_matches[0], None
        if len(exact_path_matches) > 1:
            return None, (
                f"Ambiguous refresh match for {json_path}: multiple existing statements match the same raw file path"
            )

        if len(suffix_matches) == 1:
            return suffix_matches[0], None
        if len(suffix_matches) > 1:
            return None, (
                f"Ambiguous refresh match for {json_path}: multiple existing statements match the same statement path suffix"
            )

        if len(filename_matches) == 1:
            return filename_matches[0], None
        if len(filename_matches) > 1:
            return None, (
                f"Ambiguous refresh match for {json_path}: multiple existing statements share filename {filename!r} in billing month {billing_month}"
            )
        return None, None

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[date]:
        """Parse a date string in YYYY-MM-DD format."""
        if not date_str:
            return None
        try:
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

"""
Alert Resolver Service

Handles card fee alerts: GST linking and auto-resolution of fee reversals.
Mirrors the pattern of refund_handler.py.
"""
import re
import logging
from typing import Optional, List
from datetime import date
from functools import lru_cache
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Transaction
from app.models.statement import Statement

logger = logging.getLogger(__name__)

# Words stripped when normalizing fee type for matching
STRIP_WORDS = {
    'ASSESSMENT', 'CREDIT', 'ADJUSTMENT', 'REVERSAL', 'WAIVER',
    'REBATE', 'REFUND', 'REV', 'ADJ',
    # UOB-specific: "CR CARD MEMBERSHIP FEE - INC OF GST"
    'CR', 'INC', 'INCLUSIVE', 'OF', 'GST',
}

# Patterns that identify a GST child line
GST_PREFIXES = ('GST ON ', 'GST FOR ', 'GST - ')


class AlertResolver:
    """Service for card fee alert management: GST linking and auto-resolve."""

    def __init__(self, db: Session):
        self.db = db

    def process_card_fee(self, txn: Transaction) -> bool:
        """
        Called during import for card_fees transactions.

        For charges: link GST lines to parent fee.
        For reversals: try to auto-resolve a pending/unresolved fee.

        Returns:
            True if an auto-resolve occurred, False otherwise.
        """
        if not txn.is_refund:
            self._link_gst_if_applicable(txn)
            return False

        return self._try_auto_resolve(txn)

    def _link_gst_if_applicable(self, txn: Transaction) -> None:
        """
        If this transaction's merchant_name starts with 'GST ON'/'GST FOR',
        find the parent card_fee on the same card+statement, link via
        parent_transaction_id, and clear alert_status (no separate alert).
        """
        merchant_upper = (txn.merchant_name or '').upper()
        if not any(merchant_upper.startswith(prefix) for prefix in GST_PREFIXES):
            return

        # Find the parent fee on the same statement (same card)
        parent = (
            self.db.query(Transaction)
            .filter(
                Transaction.statement_id == txn.statement_id,
                Transaction.id != txn.id,
                Transaction.is_refund == False,
                Transaction.parent_transaction_id.is_(None),  # not itself a GST child
                Transaction.categories.contains('card_fees'),
            )
            .order_by(Transaction.id.desc())  # most recent first (closest preceding)
            .first()
        )

        if parent:
            txn.parent_transaction_id = parent.id
            txn.alert_status = None  # GST child doesn't get its own alert
            logger.info(
                "Linked GST txn %s ($%.2f) to parent fee txn %s ($%.2f)",
                txn.id, txn.amount, parent.id, parent.amount,
            )

    def _try_auto_resolve(self, reversal_txn: Transaction) -> bool:
        """
        Try to auto-resolve a pending/unresolved card fee using this reversal.

        Matching: same card, fee type match, amount match (fee+GST), within +2 months.
        """
        if not reversal_txn.statement:
            reversal_txn.alert_status = 'pending'
            return False

        card_last_4 = reversal_txn.statement.card_last_4
        reversal_type = self._normalize_fee_type(reversal_txn.merchant_name or '')
        reversal_amount = abs(reversal_txn.amount)

        # Time window: look back up to 2 months before this reversal's statement date
        reversal_stmt_date = reversal_txn.statement.statement_date
        earliest_stmt_date = reversal_stmt_date - relativedelta(months=2)

        # Find candidate fees: same card, pending/unresolved, within time window
        candidates = (
            self.db.query(Transaction)
            .join(Statement)
            .filter(
                Statement.card_last_4 == card_last_4,
                Transaction.is_refund == False,
                Transaction.alert_status.in_(['pending', 'unresolved']),
                Transaction.parent_transaction_id.is_(None),  # not GST children
                Statement.statement_date >= earliest_stmt_date,
                Statement.statement_date <= reversal_stmt_date,
            )
            .all()
        )

        # Filter by fee type and amount match
        matches = []
        for fee_txn in candidates:
            fee_type = self._normalize_fee_type(fee_txn.merchant_name or '')
            if fee_type != reversal_type:
                continue
            fee_total = self._get_fee_total(fee_txn)
            if abs(fee_total - reversal_amount) < 0.01:  # float tolerance
                matches.append(fee_txn)

        if len(matches) == 1:
            # Exact single match → auto-resolve
            original_fee = matches[0]
            original_fee.alert_status = 'resolved'
            original_fee.resolved_by_transaction_id = reversal_txn.id
            original_fee.resolved_method = 'auto'
            reversal_txn.alert_status = 'resolved'
            reversal_txn.resolved_method = 'auto'
            self.db.flush()
            logger.info(
                "Auto-resolved fee txn %s ($%.2f) with reversal txn %s ($%.2f)",
                original_fee.id, original_fee.amount, reversal_txn.id, reversal_txn.amount,
            )
            return True

        elif len(matches) > 1:
            # Ambiguous — let user resolve manually
            reversal_txn.alert_status = 'pending'
            logger.info(
                "Ambiguous auto-resolve for reversal txn %s: %d candidates",
                reversal_txn.id, len(matches),
            )
            return False

        else:
            # No match — still show to user for visibility
            reversal_txn.alert_status = 'pending'
            logger.info(
                "No matching fee found for reversal txn %s ($%.2f)",
                reversal_txn.id, reversal_txn.amount,
            )
            return False

    def _normalize_fee_type(self, merchant_name: str) -> str:
        """
        Strip noise words to extract core fee type for matching.

        Examples:
            'LATE CHARGE ASSESSMENT' → 'LATE CHARGE'
            'LATE FEE CREDIT ADJUSTMENT' → 'LATE FEE'
            'FINANCE CHARGE' → 'FINANCE CHARGE'
            'ANNUAL FEE REVERSAL' → 'ANNUAL FEE'
            'CR CARD MEMBERSHIP FEE - INC OF GST' → 'CARD MEMBERSHIP FEE'
            'CARD MEMBERSHIP FEE -INCLUSIVE OF GST' → 'CARD MEMBERSHIP FEE'
        """
        # Strip punctuation so "-INCLUSIVE" splits as "INCLUSIVE", not one token
        cleaned = re.sub(r'[^A-Z0-9 ]', ' ', merchant_name.upper())
        words = cleaned.split()
        core_words = [w for w in words if w not in STRIP_WORDS]
        return ' '.join(core_words).strip()

    def _get_fee_total(self, fee_txn: Transaction) -> float:
        """Return fee amount + sum of child GST amounts."""
        total = abs(fee_txn.amount)
        children = (
            self.db.query(Transaction)
            .filter(Transaction.parent_transaction_id == fee_txn.id)
            .all()
        )
        for child in children:
            total += abs(child.amount)
        return total

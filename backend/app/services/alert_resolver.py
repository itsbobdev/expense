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
from app.services.alert_policy import (
    ACTIVE_ALERT_STATUSES,
    ALERT_KIND_CARD_FEE,
    ALERT_STATUS_PENDING,
)

logger = logging.getLogger(__name__)

# Words stripped when normalizing fee type for matching
STRIP_WORDS = {
    'ASSESSMENT', 'CREDIT', 'ADJUSTMENT', 'REVERSAL', 'WAIVER',
    'REBATE', 'REFUND', 'REV', 'ADJ',
    'BILLED',
    # UOB-specific: "CR CARD MEMBERSHIP FEE - INC OF GST"
    'CR', 'INC', 'INCLUSIVE', 'OF', 'GST',
}

# Patterns that identify a GST child line
GST_PREFIXES = ('GST ON ', 'GST FOR ', 'GST - ')
CARD_FEE_HINTS = (
    'ANNUAL FEE',
    'MEMBERSHIP FEE',
    'LATE CHARGE',
    'LATE FEE',
    'FINANCE CHARGE',
    'OVERLIMIT',
    'SERVICE CHARGE',
    'GST @',
    'GST ON ',
    'GST FOR ',
    'GST - ',
)


def looks_like_card_fee(merchant_name: str | None) -> bool:
    """Best-effort fallback for fee lines when extraction missed `card_fees`."""
    merchant_upper = (merchant_name or '').upper()
    return any(hint in merchant_upper for hint in CARD_FEE_HINTS)


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

        # Card-fee reversals belong in /alerts, not the orphan refund review queue.
        txn.needs_review = False
        txn.assignment_method = None
        already_linked_fee = (
            self.db.query(Transaction)
            .filter(Transaction.resolved_by_transaction_id == txn.id)
            .first()
        )
        if already_linked_fee:
            txn.alert_status = 'resolved'
            txn.resolved_method = already_linked_fee.resolved_method or txn.resolved_method or 'auto'
            return True
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
            reversal_txn.alert_kind = ALERT_KIND_CARD_FEE
            reversal_txn.alert_status = ALERT_STATUS_PENDING
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
                Transaction.alert_kind == ALERT_KIND_CARD_FEE,
                Transaction.alert_status.in_(ACTIVE_ALERT_STATUSES),
                Transaction.parent_transaction_id.is_(None),  # not GST children
                Statement.statement_date >= earliest_stmt_date,
                Statement.statement_date <= reversal_stmt_date,
            )
            .all()
        )

        # Filter by fee type and amount match
        matches = []
        for fee_txn in candidates:
            if not self._fee_types_match(fee_txn, reversal_txn, reversal_type):
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
            reversal_txn.alert_kind = ALERT_KIND_CARD_FEE
            reversal_txn.alert_status = ALERT_STATUS_PENDING
            logger.info(
                "Ambiguous auto-resolve for reversal txn %s: %d candidates",
                reversal_txn.id, len(matches),
            )
            return False

        else:
            # No match — still show to user for visibility
            reversal_txn.alert_kind = ALERT_KIND_CARD_FEE
            reversal_txn.alert_status = ALERT_STATUS_PENDING
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

    def _fee_types_match(
        self,
        fee_txn: Transaction,
        reversal_txn: Transaction,
        reversal_type: str,
    ) -> bool:
        """Match fee/reversal types, allowing HSBC-specific late charge synonyms."""
        fee_type = self._normalize_fee_type(fee_txn.merchant_name or '')
        if fee_type == reversal_type:
            return True

        bank_name = ((reversal_txn.statement.bank_name if reversal_txn.statement else None) or '').upper()
        if bank_name == 'UOB' and self._is_uob_uni_fee_adjustment_pair(fee_txn, reversal_txn):
            return True
        if bank_name != 'HSBC':
            return False

        return (
            self._canonical_hsbc_fee_type(fee_type)
            == self._canonical_hsbc_fee_type(reversal_type)
        )

    def _is_uob_uni_fee_adjustment_pair(
        self,
        fee_txn: Transaction,
        reversal_txn: Transaction,
    ) -> bool:
        """
        UOB sometimes represents fee charge/reversal as UNI$ adjustments with SGD 0.00.

        Example pair:
          - DEDUCTED UNI$ 6500 FOR CARD FEE $218
          - ADD UNI$ - MEMBERSHIP FEE REV 0006500

        Treat these as the same fee family for UOB only when the charge side is a
        UNI$ deduction and the reversal side is a UNI$ add-back tied to a card fee.
        """
        fee_name = (fee_txn.merchant_name or '').upper()
        reversal_name = (reversal_txn.merchant_name or '').upper()

        fee_has_uni = 'UNI$' in fee_name or 'UNI ' in fee_name
        reversal_has_uni = 'UNI$' in reversal_name or 'UNI ' in reversal_name
        if not (fee_has_uni and reversal_has_uni):
            return False

        fee_is_deduction = 'DEDUCTED' in fee_name
        reversal_is_add = 'ADD' in reversal_name
        if not (fee_is_deduction and reversal_is_add):
            return False

        fee_mentions_card_fee = 'CARD FEE' in fee_name or 'MEMBERSHIP FEE' in fee_name
        reversal_mentions_card_fee = 'CARD FEE' in reversal_name or 'MEMBERSHIP FEE' in reversal_name
        return fee_mentions_card_fee and reversal_mentions_card_fee

    def _canonical_hsbc_fee_type(self, fee_type: str) -> str:
        """Collapse HSBC naming variants that represent the same fee family."""
        if fee_type in {'LATE CHARGE', 'LATE FEE'}:
            return 'LATE_FEE_FAMILY'
        return fee_type

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

"""
Refund Handler Service

Handles automatic matching of refund transactions to their original transactions.
"""
from datetime import timedelta
from typing import List

from sqlalchemy.orm import Session

from app.models import Transaction
from app.models.statement import Statement
from app.services.linked_refund_sync import (
    delete_draft_bills_for_month,
    collect_transaction_person_ids,
    sync_linked_refund_to_original,
)


class RefundHandler:
    """Service for matching refund transactions to original transactions."""

    def __init__(self, db: Session):
        self.db = db

    def process_refund(self, refund_transaction: Transaction) -> bool:
        """
        Process a refund transaction and try to match it to an original transaction.

        Args:
            refund_transaction: The refund transaction (negative amount)

        Returns:
            True if auto-matched successfully, False if needs manual review
        """
        # Rewards are not refunds - skip matching entirely.
        if getattr(refund_transaction, "is_reward", False):
            return False

        # Step 1: Identify refund (negative amount)
        if refund_transaction.amount >= 0:
            return False

        # Step 2: Find potential original transactions
        candidates = self._find_exact_candidates(refund_transaction)

        if len(candidates) == 1:
            previous_person_ids = collect_transaction_person_ids(refund_transaction)
            self._apply_auto_match(refund_transaction, candidates[0])
            self._refresh_draft_bills_for_refund(refund_transaction, previous_person_ids)
            self.db.commit()
            return True

        if len(candidates) > 1:
            refund_transaction.is_refund = True
            refund_transaction.needs_review = True
            refund_transaction.assignment_method = "refund_ambiguous"
            refund_transaction.review_origin_method = "refund_ambiguous"
            self.db.commit()
            return False

        refund_transaction.is_refund = True
        refund_transaction.needs_review = True
        refund_transaction.assignment_method = "refund_orphan"
        refund_transaction.review_origin_method = "refund_orphan"
        self.db.commit()
        return False

    def reconcile_refunds_for_original(self, original_transaction: Transaction) -> int:
        """
        Retry older orphaned or ambiguous refunds after importing an original charge.
        """
        if original_transaction.is_refund or getattr(original_transaction, "is_reward", False):
            return 0

        candidate_refunds = (
            self.db.query(Transaction)
            .filter(
                Transaction.merchant_name == original_transaction.merchant_name,
                Transaction.amount == -original_transaction.amount,
                Transaction.transaction_date >= original_transaction.transaction_date,
                Transaction.transaction_date <= original_transaction.transaction_date + timedelta(days=180),
                Transaction.is_refund == True,
                Transaction.needs_review == True,
                Transaction.original_transaction_id.is_(None),
                Transaction.assignment_method.in_(["refund_orphan", "refund_ambiguous"]),
                Transaction.id != original_transaction.id,
            )
            .all()
        )

        resolved = 0
        for refund_transaction in candidate_refunds:
            exact_matches = self._find_exact_candidates(refund_transaction)
            if len(exact_matches) == 1 and exact_matches[0].id == original_transaction.id:
                previous_person_ids = collect_transaction_person_ids(refund_transaction)
                self._apply_auto_match(refund_transaction, original_transaction)
                self._refresh_draft_bills_for_refund(refund_transaction, previous_person_ids)
                resolved += 1

        if resolved:
            self.db.commit()

        return resolved

    def get_refund_candidates(self, refund_transaction: Transaction) -> List[Transaction]:
        """
        Get potential original transactions for a refund.

        Args:
            refund_transaction: The refund transaction

        Returns:
            List of candidate original transactions
        """
        if refund_transaction.amount >= 0:
            return []

        return self._find_exact_candidates(refund_transaction, newest_first=True)

    def get_broad_candidates(self, refund_transaction: Transaction) -> List[Transaction]:
        """
        Broader tiered search for refund matching when exact match fails.

        Tier 1: Exact merchant + exact amount (existing behavior)
        Tier 2: Same card + exact amount + 180-day window
        Tier 3: Same card + similar amount (within 10%) + 180-day window
        Tier 4: Same card + merchant name substring match + 180-day window
        """
        abs_amount = abs(refund_transaction.amount)
        earliest = refund_transaction.transaction_date - timedelta(days=180)
        card_last_4 = refund_transaction.statement.card_last_4 if refund_transaction.statement else None

        tier1 = self.get_refund_candidates(refund_transaction)
        if tier1:
            return tier1

        if not card_last_4:
            return []

        tier2 = (
            self.db.query(Transaction)
            .join(Statement)
            .filter(
                Statement.card_last_4 == card_last_4,
                Transaction.amount == abs_amount,
                Transaction.transaction_date <= refund_transaction.transaction_date,
                Transaction.transaction_date >= earliest,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id,
            )
            .order_by(Transaction.transaction_date.desc())
            .all()
        )
        if tier2:
            return tier2

        lower = abs_amount * 0.9
        upper = abs_amount * 1.1
        tier3 = (
            self.db.query(Transaction)
            .join(Statement)
            .filter(
                Statement.card_last_4 == card_last_4,
                Transaction.amount.between(lower, upper),
                Transaction.transaction_date <= refund_transaction.transaction_date,
                Transaction.transaction_date >= earliest,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id,
            )
            .order_by(Transaction.transaction_date.desc())
            .all()
        )
        if tier3:
            return tier3

        refund_merchant = refund_transaction.merchant_name.upper()
        same_card_txns = (
            self.db.query(Transaction)
            .join(Statement)
            .filter(
                Statement.card_last_4 == card_last_4,
                Transaction.transaction_date <= refund_transaction.transaction_date,
                Transaction.transaction_date >= earliest,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id,
            )
            .order_by(Transaction.transaction_date.desc())
            .all()
        )
        tier4 = [
            t
            for t in same_card_txns
            if t.merchant_name
            and (t.merchant_name.upper() in refund_merchant or refund_merchant in t.merchant_name.upper())
        ]
        if tier4:
            return tier4

        return []

    def search_by_amount(self, refund_transaction: Transaction, limit: int = 10) -> List[Transaction]:
        """Search all non-refund transactions matching the absolute refund amount."""
        abs_amount = abs(refund_transaction.amount)
        return (
            self.db.query(Transaction)
            .filter(
                Transaction.amount == abs_amount,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id,
            )
            .order_by(Transaction.transaction_date.desc())
            .limit(limit)
            .all()
        )

    def match_refund_manually(
        self,
        refund_transaction_id: int,
        original_transaction_id: int,
    ) -> Transaction:
        """
        Manually match a refund to an original transaction.

        Args:
            refund_transaction_id: ID of the refund transaction
            original_transaction_id: ID of the original transaction

        Returns:
            The updated refund transaction

        Raises:
            ValueError: If transactions not found or invalid
        """
        refund = self.db.query(Transaction).filter(Transaction.id == refund_transaction_id).first()
        original = self.db.query(Transaction).filter(Transaction.id == original_transaction_id).first()

        if not refund or not original:
            raise ValueError("Transaction not found")

        if refund.amount >= 0:
            raise ValueError("Not a refund transaction (amount must be negative)")

        previous_person_ids = collect_transaction_person_ids(refund)
        refund.assignment_method = "refund_manual_match"
        refund.assignment_confidence = 1.0
        sync_linked_refund_to_original(refund, original)
        self._refresh_draft_bills_for_refund(refund, previous_person_ids)

        self.db.commit()
        self.db.refresh(refund)

        return refund

    def _find_exact_candidates(
        self,
        refund_transaction: Transaction,
        newest_first: bool = False,
    ) -> List[Transaction]:
        """Find exact merchant+amount matches within the refund lookback window."""
        original_amount = -refund_transaction.amount
        earliest_date = refund_transaction.transaction_date - timedelta(days=180)

        query = (
            self.db.query(Transaction)
            .filter(
                Transaction.merchant_name == refund_transaction.merchant_name,
                Transaction.amount == original_amount,
                Transaction.transaction_date <= refund_transaction.transaction_date,
                Transaction.transaction_date >= earliest_date,
                Transaction.is_refund == False,
                Transaction.id != refund_transaction.id,
            )
        )

        if newest_first:
            query = query.order_by(Transaction.transaction_date.desc())

        return query.all()

    @staticmethod
    def _apply_auto_match(refund_transaction: Transaction, original_transaction: Transaction) -> None:
        """Apply the canonical auto-match fields to a refund transaction."""
        refund_transaction.assignment_method = "refund_auto_match"
        refund_transaction.assignment_confidence = 0.95
        sync_linked_refund_to_original(refund_transaction, original_transaction)

    def _refresh_draft_bills_for_refund(
        self,
        refund_transaction: Transaction,
        previous_person_ids: set[int] | None = None,
    ) -> None:
        affected_person_ids = set(previous_person_ids or set())
        affected_person_ids.update(collect_transaction_person_ids(refund_transaction))
        delete_draft_bills_for_month(self.db, refund_transaction.billing_month, affected_person_ids)
